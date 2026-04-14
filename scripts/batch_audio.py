#!/usr/bin/env python3
"""
batch_audio.py — Execute the `audio:` section of an action-items spec file
against the ElevenLabs API.

What it does per audio item:
  1. Generate a new TTS excerpt via ElevenLabs with the project's cloned voice.
  2. Run silence detection on the output to catch anomalies.
  3. If the item declares `placement:`, record the placement intent in state
     (target Premiere sequence + start time). THE SCRIPT DOES NOT SPLICE INTO
     THE ORIGINAL VO — that would bake the correction into a monolithic master
     and destroy the ability to A/B or revert individual excerpts.

The excerpt file is the atomic unit. It is imported into Premiere as a clip,
placed on a new audio track (A3/A4) at the declared start_time. The original
v1 VO stays on A1 untouched, and the mix decides which to play.

Same design principles as batch_video.py:
  - Sequential
  - Idempotent (skips outputs that already exist)
  - Log-skip-continue on failures
  - Persistent state file next to the spec
  - Zero-token: Claude authors the spec, humans run the script.

Usage:
    python3 batch_audio.py action_items_v1.yaml
    python3 batch_audio.py action_items_v1.yaml --dry-run
    python3 batch_audio.py action_items_v1.yaml --only A1,A2
    python3 batch_audio.py action_items_v1.yaml --retry-failed
    python3 batch_audio.py action_items_v1.yaml --force

Spec format:

    project: cend
    version: 1
    audio:
      - id: A1
        description: "Regenerar 'liability' en comercial"
        voice_id: "p0i9gxggdbxx7u0SPXk1"      # ElevenLabs cloned voice
        model: "eleven_multilingual_v2"       # optional, default shown
        stability: 0.5                        # optional
        similarity_boost: 0.85                # optional
        style: 0.3                            # optional
        text: "Your supply chain is a liability."
        output: "Assets/Audio/Voz/Comercial/A1_v1_excerpt.mp3"
        # Optional placement metadata (informational — consumed by the Premiere
        # import step, NOT by this script):
        placement:
          target_sequence: "Comercial"        # which Premiere sequence to place the excerpt in
          start_time: 0.0                     # seconds into that sequence
          original_phrase_range: [0.0, 3.0]   # docs: the v1 said this phrase here

The ElevenLabs API key is read from config.local.json → elevenlabs.api_key, or
from Referencia/API Keys.md (fallback).

Default voice settings (if not in spec):
    stability: 0.5
    similarity_boost: 0.85
    style: 0.3
"""

import argparse
import json
import subprocess
import sys
import traceback
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
from video_gen import load_merged_config  # reuse the same config loader  # noqa: E402


# ---------------------------------------------------------------------------
# ElevenLabs API key resolution
# ---------------------------------------------------------------------------

def get_elevenlabs_key() -> str:
    # 1) config.local.json → elevenlabs.api_key
    cfg = load_merged_config()
    if "elevenlabs" in cfg and cfg["elevenlabs"].get("api_key"):
        return cfg["elevenlabs"]["api_key"]

    # 2) Fallback: Referencia/API Keys.md (scan for a line starting with sk_)
    for candidate in [
        SCRIPT_DIR.parent.parent / "Referencia" / "API Keys.md",
        Path.home() / "Downloads" / "Cend" / "Referencia" / "API Keys.md",
    ]:
        if candidate.exists():
            for line in candidate.read_text().splitlines():
                line = line.strip()
                if line.startswith("sk_"):
                    return line
    raise RuntimeError(
        "ElevenLabs API key not found. Add to config.local.json under "
        "`elevenlabs.api_key` or place a bare `sk_...` line in Referencia/API Keys.md"
    )


# ---------------------------------------------------------------------------
# State file — same pattern as batch_video.py
# ---------------------------------------------------------------------------

class BatchState:
    def __init__(self, spec_path: Path):
        # Use a distinct state file so audio and video don't stomp on each other
        self.path = spec_path.with_suffix(spec_path.suffix + ".audio.state.json")
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text())
            except Exception:
                self.data = {}
        else:
            self.data = {}

    def get(self, slot_id: str) -> dict:
        return self.data.get(slot_id, {})

    def set(self, slot_id: str, **kwargs):
        entry = self.data.get(slot_id, {})
        entry.update(kwargs)
        entry["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self.data[slot_id] = entry
        self._save()

    def _save(self):
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# ElevenLabs client (stdlib only)
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "eleven_multilingual_v2"
DEFAULT_SETTINGS = {"stability": 0.5, "similarity_boost": 0.85, "style": 0.3}


def tts_request(api_key: str, voice_id: str, text: str,
                model: str = DEFAULT_MODEL, settings: Optional[dict] = None) -> bytes:
    """Call ElevenLabs TTS and return the raw MP3 bytes."""
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    body = {
        "text": text,
        "model_id": model,
        "voice_settings": {**DEFAULT_SETTINGS, **(settings or {})},
    }
    req = urllib.request.Request(
        url, method="POST",
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        data=json.dumps(body).encode("utf-8"),
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


# ---------------------------------------------------------------------------
# ffmpeg helpers
# ---------------------------------------------------------------------------

def probe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(r.stdout.strip())


def _write_audio_prompt_sidecar(output: Path, item: dict):
    """Write `<output>.prompt.txt` with the TTS text + voice settings used.
    Best-effort: failures don't break the batch."""
    sidecar = output.with_suffix(output.suffix + ".prompt.txt")
    try:
        content = (
            f"# {output.name}\n"
            f"slot:            {item['id']}\n"
            f"piece:           {item.get('piece', '')}\n"
            f"voice_id:        {item.get('voice_id', '')}\n"
            f"model:           {item.get('model', DEFAULT_MODEL)}\n"
            f"stability:       {item.get('stability', 0.5)}\n"
            f"similarity_boost:{item.get('similarity_boost', 0.85)}\n"
            f"style:           {item.get('style', 0.3)}\n"
            f"description:     {item.get('description', '')}\n"
            f"\n--- TEXT ---\n{item.get('text', '')}\n"
        )
        sidecar.write_text(content)
    except Exception as e:
        print(f"  ⚠ sidecar write failed for {output.name}: {e}", flush=True)


def detect_silences(path: Path, noise_db: int = -30, min_duration: float = 1.5) -> list:
    """Return a list of (start, end, duration) silence intervals."""
    r = subprocess.run(
        ["ffmpeg", "-i", str(path),
         "-af", f"silencedetect=noise={noise_db}dB:d={min_duration}",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    silences = []
    start = None
    for line in r.stderr.splitlines():
        if "silence_start:" in line:
            start = float(line.split("silence_start:")[1].strip())
        elif "silence_end:" in line and start is not None:
            rest = line.split("silence_end:")[1].strip()
            end_str, dur_str = rest.split("|")
            end = float(end_str.strip())
            dur = float(dur_str.split(":")[1].strip())
            silences.append((start, end, dur))
            start = None
    return silences


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class AudioBatchRunner:
    def __init__(self, spec_path: Path, args):
        self.spec_path = spec_path
        self.args = args
        self.spec = yaml.safe_load(spec_path.read_text())
        self.state = BatchState(spec_path)

        self.project_id = self.spec.get("project")
        if not self.project_id:
            raise ValueError("Spec must define `project` at top level")
        cfg = load_merged_config()
        roots = cfg.get("project_roots") or {}
        if self.project_id not in roots:
            raise ValueError(f"project_roots[{self.project_id!r}] not defined")
        self.project_root = Path(roots[self.project_id]).expanduser()
        if not self.project_root.exists():
            raise FileNotFoundError(f"Project root missing: {self.project_root}")

        self.api_key = None if args.dry_run else get_elevenlabs_key()

    def _log(self, msg: str):
        print("  " + msg, flush=True)

    def _should_skip_item(self, item: dict, output: Path) -> Optional[str]:
        if self.args.only:
            ids = [x.strip() for x in self.args.only.split(",")]
            if item["id"] not in ids:
                return f"not in --only={self.args.only}"
        if self.args.force:
            return None
        state = self.state.get(item["id"])
        if output.exists():
            return f"already exists at {output.name}"
        if self.args.retry_failed and state.get("status") != "failed":
            return f"skipping (retry-failed mode, status={state.get('status', 'unset')})"
        return None

    def run_item(self, item: dict) -> str:
        output = self.project_root / item["output"]

        skip = self._should_skip_item(item, output)
        if skip:
            self._log(f"⊘ {item['id']}: {skip}")
            return "skipped"

        print()
        print(f"═══ {item['id']}  ·  {item.get('description', '')}")
        self._log(f'text: "{item["text"]}"')
        self._log(f"output: {output.relative_to(self.project_root)}")

        if self.args.dry_run:
            self._log("(dry-run — not calling ElevenLabs)")
            if item.get("placement"):
                p = item["placement"]
                self._log(f"placement intent: sequence={p.get('target_sequence')!r} start={p.get('start_time')}s")
            return "dry-run"

        # 1) Generate TTS
        try:
            audio_bytes = tts_request(
                api_key=self.api_key,
                voice_id=item["voice_id"],
                text=item["text"],
                model=item.get("model", DEFAULT_MODEL),
                settings={
                    "stability": item.get("stability", 0.5),
                    "similarity_boost": item.get("similarity_boost", 0.85),
                    "style": item.get("style", 0.3),
                },
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(audio_bytes)
            _write_audio_prompt_sidecar(output, item)
            self._log(f"✓ generated {len(audio_bytes)} bytes → {output.name}")
            self.state.set(item["id"], status="generated",
                           output=str(output),
                           bytes=len(audio_bytes))
        except Exception as exc:
            self._log(f"✗ TTS failed: {exc}")
            self.state.set(item["id"], status="failed", error=str(exc),
                           traceback=traceback.format_exc(limit=2))
            return "failed"

        # 2) Silence sanity check on the new segment
        try:
            silences = detect_silences(output, noise_db=-30, min_duration=1.0)
            if silences:
                self._log(f"⚠  detected {len(silences)} silent region(s): {silences}")
                self.state.set(item["id"], silences=silences)
        except Exception as exc:
            self._log(f"  (silence probe skipped: {exc})")

        # 3) Record placement intent (if declared). The actual placement
        #    happens in Premiere via the import step — this script never
        #    splices the excerpt into an existing VO, because that bakes the
        #    correction into a monolithic master and destroys atomic revert.
        if item.get("placement"):
            p = item["placement"]
            try:
                excerpt_dur = probe_duration(output)
            except Exception:
                excerpt_dur = None
            placement = {
                "target_sequence": p.get("target_sequence"),
                "start_time": p.get("start_time"),
                "original_phrase_range": p.get("original_phrase_range"),
                "excerpt_duration": excerpt_dur,
            }
            self._log(
                f"placement: {placement['target_sequence']!r} @ {placement['start_time']}s "
                f"(excerpt {excerpt_dur:.2f}s vs v1 range {p.get('original_phrase_range')})"
                if excerpt_dur else
                f"placement: {placement['target_sequence']!r} @ {placement['start_time']}s"
            )
            self.state.set(item["id"], status="done", placement=placement)
            return "done"

        self.state.set(item["id"], status="done")
        return "done"

    def run(self):
        items = self.spec.get("audio", [])
        if not items:
            self._log("No items in audio: section")
            return

        print()
        print("╔" + "═" * 68 + "╗")
        print(f"║  BATCH AUDIO  ·  {self.project_id}  ·  v{self.spec.get('version', '?')}".ljust(69) + "║")
        print(f"║  {len(items)} items".ljust(69) + "║")
        if self.args.dry_run:
            print("║  MODE: DRY-RUN".ljust(69) + "║")
        print("╚" + "═" * 68 + "╝")

        counts = {"done": 0, "generated": 0, "failed": 0, "skipped": 0, "dry-run": 0}
        for item in items:
            result = self.run_item(item)
            counts[result] = counts.get(result, 0) + 1

        print()
        print("─" * 70)
        parts = [f"{k}={v}" for k, v in counts.items() if v]
        print(f"  Totals: {'  '.join(parts)}")
        print(f"  State file: {self.state.path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", type=Path, help="Path to the YAML spec file")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", type=str, default=None,
                    help="Comma-separated list of slot IDs (e.g. A1,A2)")
    ap.add_argument("--retry-failed", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if not args.spec.exists():
        print(f"ERROR: spec file not found: {args.spec}", file=sys.stderr)
        sys.exit(1)

    runner = AudioBatchRunner(args.spec.resolve(), args)
    runner.run()


if __name__ == "__main__":
    main()
