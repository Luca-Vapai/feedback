#!/usr/bin/env python3
"""
batch_video.py — Execute the `video:` section of an action-items spec file
against the SOUTS video generation API.

Design goals:
  - Sequential execution (one job at a time, respects the shared server).
  - Idempotent: skips any output file that already exists on disk.
  - Log-skip-continue on failures. A JSON state file tracks success/failure per
    alternative so re-running the spec only retries what's pending.
  - Zero-token workflow: Claude authors the YAML spec, humans run this script,
    everything happens without the assistant in the loop.

Usage:
    # Run the whole video batch
    python3 batch_video.py action_items_v1.yaml

    # Dry-run: show what would happen, don't touch the server
    python3 batch_video.py action_items_v1.yaml --dry-run

    # Only run a subset (by slot ID, comma-separated)
    python3 batch_video.py action_items_v1.yaml --only C2,C7

    # Re-run failed items only
    python3 batch_video.py action_items_v1.yaml --retry-failed

    # Force re-generation of everything, even files that already exist
    python3 batch_video.py action_items_v1.yaml --force

Spec format (see SOUTS Video Gen API — Guide.md for context):

    project: cend
    version: 1
    video:
      - id: C2
        description: "…"
        piece: commercial                  # used to resolve output paths
        workflow: LTX23_T2V_Basic          # workflow template name
        width: 1280
        height: 720
        fps: 24
        length: 5                          # seconds (LTX interprets LENGTH this way)
        prompts:
          - alt: 1
            prompt: "…"
          - alt: 2
            prompt: "…"
          - alt: 3
            prompt: "…"
          - alt: 4
            prompt: "…"
        output_dir: "Video/GenAI/Comercial"   # relative to project_root
        output_pattern: "C2_v1_alt{n}.mp4"    # {n} → alt number

The project root is resolved from Feedback web/config.local.json → project_roots[project].
"""

import argparse
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import List, Optional

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

# Local import of the SOUTS wrapper
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from video_gen import SoutsVideoGen, load_merged_config   # noqa: E402


# ---------------------------------------------------------------------------
# State file — tracks which alternatives have been generated / failed
# ---------------------------------------------------------------------------

class BatchState:
    """Persists per-alternative status next to the spec file."""

    def __init__(self, spec_path: Path):
        self.path = spec_path.with_suffix(spec_path.suffix + ".state.json")
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text())
            except Exception:
                self.data = {}
        else:
            self.data = {}

    def key(self, slot_id: str, alt: int) -> str:
        return f"{slot_id}:alt{alt}"

    def get(self, slot_id: str, alt: int) -> dict:
        return self.data.get(self.key(slot_id, alt), {})

    def set(self, slot_id: str, alt: int, **kwargs):
        k = self.key(slot_id, alt)
        entry = self.data.get(k, {})
        entry.update(kwargs)
        entry["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self.data[k] = entry
        self._save()

    def _save(self):
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class VideoBatchRunner:
    def __init__(self, spec_path: Path, args):
        self.spec_path = spec_path
        self.args = args
        self.spec = yaml.safe_load(spec_path.read_text())
        self.state = BatchState(spec_path)
        self.gen = SoutsVideoGen(quiet=False) if not args.dry_run else None

        # Resolve project root
        self.project_id = self.spec.get("project")
        if not self.project_id:
            raise ValueError("Spec must define `project` at top level")
        cfg = load_merged_config()
        roots = cfg.get("project_roots") or {}
        if self.project_id not in roots:
            raise ValueError(
                f"project_roots[{self.project_id!r}] not defined in config.local.json. "
                f"Add it first so the runner knows where to write outputs."
            )
        self.project_root = Path(roots[self.project_id]).expanduser()
        if not self.project_root.exists():
            raise FileNotFoundError(f"Project root does not exist: {self.project_root}")

    def _log(self, msg: str, indent: int = 0):
        print(("  " * indent) + msg, flush=True)

    def _output_path(self, item: dict, alt: int) -> Path:
        output_dir = self.project_root / item["output_dir"]
        pattern = item.get("output_pattern", "{id}_alt{n}.mp4")
        filename = pattern.format(n=alt, id=item["id"])
        return output_dir / filename

    def _should_skip_item(self, item: dict) -> Optional[str]:
        if self.args.only:
            ids = [x.strip() for x in self.args.only.split(",")]
            if item["id"] not in ids:
                return f"not in --only={self.args.only}"
        return None

    def _should_skip_alt(self, item: dict, alt: int, output: Path) -> Optional[str]:
        if self.args.force:
            return None
        state = self.state.get(item["id"], alt)
        if output.exists():
            return f"already exists at {output.name}"
        if self.args.retry_failed:
            if state.get("status") != "failed":
                return f"skipping (retry-failed mode, status={state.get('status', 'unset')})"
        return None

    # ----- helpers shared by both modes --------------------------------------

    def _write_prompt_sidecar(self, output: Path, item: dict, alt: int, prompt: str):
        """Write a `<output>.prompt.txt` next to the video with the prompt
        used and minimal metadata. This is for human/agent traceability —
        once a v2/v3/... batch ships, anyone can open the sidecar to know
        exactly what produced this clip without grepping the spec."""
        sidecar = output.with_suffix(output.suffix + ".prompt.txt")
        try:
            content = (
                f"# {output.name}\n"
                f"slot:        {item['id']}\n"
                f"alt:         {alt}\n"
                f"piece:       {item.get('piece', '')}\n"
                f"workflow:    {item['workflow']}\n"
                f"size:        {item['width']}x{item['height']}\n"
                f"fps:         {item['fps']}\n"
                f"length:      {item['length']}s\n"
                f"description: {item.get('description', '')}\n"
                f"script_context: {item.get('script_context', '')}\n"
                f"\n--- PROMPT ---\n{prompt}\n"
            )
            sidecar.parent.mkdir(parents=True, exist_ok=True)
            sidecar.write_text(content)
        except Exception as e:
            # Sidecars are best-effort; don't fail the batch if disk hiccups.
            self._log(f"      ⚠ sidecar write failed for {output.name}: {e}")

    def _build_params(self, item: dict, prompt: str) -> Optional[dict]:
        """Build the workflow parameters dict, including any uploaded images.
        Returns None on upload failure (caller marks the alt as failed)."""
        params = {
            "PROMPT": prompt,
            "WIDTH": item["width"],
            "HEIGHT": item["height"],
            "FPS": item["fps"],
            "LENGTH": item["length"],
        }
        for key in ("first_frame", "middle_frame", "last_frame"):
            if item.get(key):
                img_path = self.project_root / item[key]
                try:
                    uploaded = self.gen.upload_image(img_path)
                    params[key.upper() + "_FILENAME"] = uploaded
                    self._log(f"      uploaded {key}: {uploaded}")
                except Exception as e:
                    self._log(f"      ✗ upload {key} failed: {e}")
                    return None
        return params

    def _collect_pending(self) -> List[dict]:
        """Walk the spec and return a list of pending alternatives.
        Each entry: {item, alt, prompt, output} ready to submit/process."""
        pending = []
        for item in self.spec.get("video", []):
            skip_reason = self._should_skip_item(item)
            if skip_reason:
                self._log(f"⊘ {item['id']}: {skip_reason}")
                continue

            self._log("")
            self._log(f"═══ {item['id']}  ·  {item.get('description', '')}")
            if item.get("script_context"):
                self._log(f'    "{item["script_context"]}"')
            self._log(f"    workflow: {item['workflow']}  "
                      f"{item['width']}x{item['height']}  "
                      f"{item['fps']}fps  length={item['length']}s")

            for prompt_entry in item.get("prompts", []):
                alt = prompt_entry["alt"]
                prompt = prompt_entry["prompt"]
                output = self._output_path(item, alt)
                skip = self._should_skip_alt(item, alt, output)
                if skip:
                    self._log(f"  alt{alt}: ⊘ {skip}")
                    continue
                pending.append({
                    "item": item,
                    "alt": alt,
                    "prompt": prompt,
                    "output": output,
                })
                self._log(f"  alt{alt}: pending → {output.relative_to(self.project_root)}")
        return pending

    # ----- mode A: parallel (default) ----------------------------------------
    #
    # Phase 1 — submit ALL pending alternatives to the queue up front.
    # Phase 2 — poll the API in a loop, downloading each result as it lands.
    #
    # Why this is better than sequential for queue-backed servers:
    #   - The server's GPU stays busy: as soon as one job finishes, the next
    #     in the queue starts immediately. No idle gap while we re-submit.
    #   - The CLI is more responsive: results arrive in submission order but
    #     we can download in parallel with the next ones still cooking.
    #   - Recovery is easier: if the script dies between submit and download,
    #     the state file already has the prompt_ids, and a re-run with the
    #     parallel runner can pick them up by checking the queue and history.

    def _run_parallel(self, pending: List[dict]) -> dict:
        stats = {"attempted": 0, "generated": 0, "failed": 0}
        if self.args.dry_run:
            self._log("")
            self._log(f"(dry-run) would submit {len(pending)} job(s) to the queue then poll")
            return stats
        if not pending:
            return stats

        # Phase 1: submit all
        self._log("")
        self._log(f"┌─ Phase 1: submitting {len(pending)} job(s) to the queue")
        in_flight = []   # list of dicts with item, alt, prompt_id, output, started_at
        for entry in pending:
            item = entry["item"]
            alt = entry["alt"]
            prompt = entry["prompt"]
            output = entry["output"]
            stats["attempted"] += 1

            params = self._build_params(item, prompt)
            if params is None:
                self.state.set(item["id"], alt, status="failed",
                               error="upload of reference image failed")
                stats["failed"] += 1
                continue

            try:
                prompt_id = self.gen.submit(item["workflow"], params,
                                            client_id=f"batch-{item['id']}-alt{alt}")
                self.state.set(item["id"], alt, status="queued",
                               prompt_id=prompt_id,
                               started_at=datetime.now().isoformat(timespec="seconds"))
                in_flight.append({
                    "item": item, "alt": alt, "output": output,
                    "prompt": prompt,
                    "prompt_id": prompt_id, "started_at": time.time(),
                })
                self._log(f"  ✓ {item['id']}:alt{alt} → {prompt_id}")
            except Exception as exc:
                tb = traceback.format_exc(limit=2)
                self._log(f"  ✗ {item['id']}:alt{alt} submit failed: {exc}")
                self.state.set(item["id"], alt, status="failed",
                               error=str(exc), traceback=tb)
                stats["failed"] += 1

        # Phase 2: poll loop
        self._log("")
        self._log(f"┌─ Phase 2: polling {len(in_flight)} in-flight job(s)")
        deadline = time.time() + self.args.timeout * max(1, len(in_flight))
        last_progress_log = 0.0
        while in_flight:
            if time.time() > deadline:
                self._log(f"⚠ poll-loop deadline hit; {len(in_flight)} job(s) still pending")
                for j in in_flight:
                    self.state.set(j["item"]["id"], j["alt"], status="failed",
                                   error="poll-loop timeout")
                    stats["failed"] += 1
                break

            still_in_flight = []
            done_this_cycle = 0
            for j in in_flight:
                try:
                    history = self.gen.get_history(j["prompt_id"])
                    entry = history.get(j["prompt_id"]) if history else None
                except Exception as exc:
                    # Transient error — keep polling next cycle
                    self._log(f"  ⚠ poll error for {j['item']['id']}:alt{j['alt']}: {exc}")
                    still_in_flight.append(j)
                    continue

                if not entry:
                    still_in_flight.append(j)
                    continue

                status_obj = entry.get("status") or {}
                if status_obj.get("status_str") == "error":
                    err_msg = json.dumps(status_obj)[:300]
                    self._log(f"  ✗ {j['item']['id']}:alt{j['alt']} server error: {err_msg}")
                    self.state.set(j["item"]["id"], j["alt"], status="failed",
                                   error=f"server error: {err_msg}")
                    stats["failed"] += 1
                    done_this_cycle += 1
                    continue

                if not (entry.get("outputs") or status_obj.get("completed")):
                    still_in_flight.append(j)
                    continue

                # We have a finished job — download it
                try:
                    desc = self.gen.find_video_in_outputs(entry)
                    if not desc:
                        raise RuntimeError(f"no video in outputs: {json.dumps(entry)[:200]}")
                    url = self.gen.build_comfyui_download_url(desc)
                    j["output"].parent.mkdir(parents=True, exist_ok=True)
                    self.gen.download_file(url, j["output"])
                    self._write_prompt_sidecar(j["output"], j["item"], j["alt"], j["prompt"])
                    duration = round(time.time() - j["started_at"], 1)
                    self.state.set(j["item"]["id"], j["alt"], status="done",
                                   prompt_id=j["prompt_id"],
                                   output=str(j["output"]),
                                   server_filename=desc.get("filename"),
                                   duration_seconds=duration)
                    self._log(f"  ✓ done {j['item']['id']}:alt{j['alt']} in {duration}s")
                    stats["generated"] += 1
                    done_this_cycle += 1
                except Exception as exc:
                    tb = traceback.format_exc(limit=2)
                    self._log(f"  ✗ download failed for {j['item']['id']}:alt{j['alt']}: {exc}")
                    self.state.set(j["item"]["id"], j["alt"], status="failed",
                                   error=f"download: {exc}", traceback=tb)
                    stats["failed"] += 1
                    done_this_cycle += 1

            in_flight = still_in_flight

            # Periodic progress log even when nothing changed this cycle
            if in_flight and (time.time() - last_progress_log > 30) and done_this_cycle == 0:
                self._log(f"  …{len(in_flight)} still in flight")
                last_progress_log = time.time()

            if in_flight:
                time.sleep(self.args.poll)

        return stats

    # ----- mode B: sequential (kept for compatibility) -----------------------

    def _run_sequential(self, pending: List[dict]) -> dict:
        stats = {"attempted": 0, "generated": 0, "failed": 0}
        if self.args.dry_run:
            for entry in pending:
                self._log(f"  (dry-run) {entry['item']['id']}:alt{entry['alt']}")
            return stats

        for entry in pending:
            item = entry["item"]
            alt = entry["alt"]
            output = entry["output"]
            stats["attempted"] += 1

            params = self._build_params(item, entry["prompt"])
            if params is None:
                self.state.set(item["id"], alt, status="failed",
                               error="upload of reference image failed")
                stats["failed"] += 1
                continue

            started_at = time.time()
            try:
                prompt_id = self.gen.submit(item["workflow"], params,
                                            client_id=f"batch-{item['id']}-alt{alt}")
                self.state.set(item["id"], alt, status="running",
                               prompt_id=prompt_id,
                               started_at=datetime.now().isoformat(timespec="seconds"))
                entry_h = self.gen.wait_for_completion(prompt_id,
                                                       poll_interval=self.args.poll,
                                                       timeout=self.args.timeout)
                desc = self.gen.find_video_in_outputs(entry_h)
                if not desc:
                    raise RuntimeError(f"no video in outputs: {json.dumps(entry_h)[:300]}")
                url = self.gen.build_comfyui_download_url(desc)
                output.parent.mkdir(parents=True, exist_ok=True)
                self.gen.download_file(url, output)
                self._write_prompt_sidecar(output, item, alt, entry["prompt"])
                duration = round(time.time() - started_at, 1)
                self.state.set(item["id"], alt, status="done",
                               prompt_id=prompt_id,
                               output=str(output),
                               server_filename=desc.get("filename"),
                               duration_seconds=duration)
                self._log(f"  ✓ done {item['id']}:alt{alt} in {duration}s")
                stats["generated"] += 1
            except Exception as exc:
                tb = traceback.format_exc(limit=2)
                self._log(f"  ✗ {item['id']}:alt{alt} failed: {exc}")
                self.state.set(item["id"], alt, status="failed",
                               error=str(exc), traceback=tb)
                stats["failed"] += 1

        return stats

    # ----- batch entrypoint --------------------------------------------------

    def run(self):
        items = self.spec.get("video", [])
        if not items:
            self._log("No items in video: section")
            return

        total_slots = len(items)
        total_alts = sum(len(i.get("prompts", [])) for i in items)

        print()
        print("╔" + "═" * 68 + "╗")
        print(f"║  BATCH VIDEO  ·  {self.project_id}  ·  v{self.spec.get('version', '?')}".ljust(69) + "║")
        print(f"║  {total_slots} slots  ·  {total_alts} alternatives  ·  mode={self.args.mode}".ljust(69) + "║")
        if self.args.dry_run:
            print("║  MODE: DRY-RUN".ljust(69) + "║")
        print("╚" + "═" * 68 + "╝")

        pending = self._collect_pending()
        skipped = total_alts - len(pending)

        if self.args.mode == "parallel":
            stats = self._run_parallel(pending)
        else:
            stats = self._run_sequential(pending)

        print()
        print("─" * 70)
        print(f"  Totals: attempted={stats['attempted']}  "
              f"generated={stats['generated']}  "
              f"skipped={skipped}  "
              f"failed={stats['failed']}")
        print(f"  State file: {self.state.path}")
        if stats["failed"]:
            print(f"  ⚠  Re-run with --retry-failed to retry only the failed items.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", type=Path, help="Path to the YAML spec file")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would happen without touching the server")
    ap.add_argument("--only", type=str, default=None,
                    help="Comma-separated list of slot IDs to run (e.g. C2,C7)")
    ap.add_argument("--retry-failed", action="store_true",
                    help="Only run items that are marked as failed in the state file")
    ap.add_argument("--force", action="store_true",
                    help="Ignore existing output files and regenerate everything")
    ap.add_argument("--poll", type=int, default=8,
                    help="Seconds between history polls (default: 8)")
    ap.add_argument("--timeout", type=int, default=1800,
                    help="Per-job timeout in seconds (default: 1800 = 30min)")
    ap.add_argument("--mode", choices=["parallel", "sequential"], default="parallel",
                    help="parallel: submit ALL jobs to the queue then poll for results "
                         "(default — uses the server queue properly). "
                         "sequential: submit one, wait, download, submit next.")
    args = ap.parse_args()

    if not args.spec.exists():
        print(f"ERROR: spec file not found: {args.spec}", file=sys.stderr)
        sys.exit(1)

    runner = VideoBatchRunner(args.spec.resolve(), args)
    runner.run()


if __name__ == "__main__":
    main()
