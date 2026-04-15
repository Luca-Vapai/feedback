#!/usr/bin/env python3
"""
upscale_clips.py — On-demand batch upscaler for sub-resolution video clips.

Scans a project's Assets/Video/** folders, filters clips below the sequence
resolution via ffprobe, submits each to the SOUTS `SeedVR2VideoUpscale`
workflow, and downloads the upscaled result with a next-version filename
per `Documentación/Nomenclatura.md`.

The Premiere-side relink + rescale is intentionally out of scope for this
script — it's done interactively via the Premiere MCP by Claude after the
batch finishes (the MCP exposes `relink_media` + `set_clip_properties`
with a simple prompt).

State lives at `Feedback web/projects/<project_id>/upscale_state.json`.
Re-running skips `status: done` entries unless --force.

Usage:
  python3 upscale_clips.py --project cend
  python3 upscale_clips.py --project cend --force
  python3 upscale_clips.py --project cend --dry-run
  python3 upscale_clips.py --project cend --scan-dir /extra/path

Defaults:
  sequence    1920x1080
  resolution  2160p (SOUTS RESOLUTION param)
  workflow    SeedVR2VideoUpscale
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

import video_utils  # noqa: E402
from video_gen import SoutsVideoGen, load_merged_config  # noqa: E402


WORKFLOW = "SeedVR2VideoUpscale"
DEFAULT_RESOLUTION = "2160p"


def log(msg, prefix="  "):
    print(f"{prefix}{msg}", flush=True)


def err(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def project_root(project_id):
    cfg = load_merged_config()
    roots = cfg.get("project_roots") or {}
    if project_id not in roots:
        err(f"project_roots[{project_id!r}] missing in Feedback web/config.local.json")
    return Path(roots[project_id]).expanduser()


def load_state(project_id):
    p = REPO_ROOT / "projects" / project_id / "upscale_state.json"
    if p.exists():
        return p, json.loads(p.read_text())
    return p, {}


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def gather_candidates(root, seq_wh, scan_dirs, prev_state, force):
    sw, sh = seq_wh
    items = []
    for d in scan_dirs:
        d = (root / d) if not d.is_absolute() else d
        if not d.exists():
            log(f"  scan: {d} (missing, skip)")
            continue
        log(f"  scan: {d}")
        for ext in ("*.mp4", "*.mov"):
            for path in sorted(d.rglob(ext)):
                rel = str(path.relative_to(root))
                if not force and prev_state.get(rel, {}).get("status") == "done":
                    continue
                try:
                    wh = video_utils.probe_resolution(path)
                except Exception as exc:
                    log(f"  skip {path.name}: probe failed ({exc})")
                    continue
                if video_utils.is_sub_resolution(wh, (sw, sh)):
                    items.append((path, rel, wh))
    return items


def run_batch(items, resolution, dry_run):
    gen = SoutsVideoGen() if not dry_run else None
    results = []
    for path, rel, wh in items:
        target = video_utils.next_version_path(path)
        if dry_run:
            log(f"[dry] {rel} ({wh[0]}x{wh[1]}) → {target.name}")
            results.append({"rel": rel, "status": "dry", "target": str(target)})
            continue
        log(f"→ {rel} ({wh[0]}x{wh[1]}) → {target.name}")
        try:
            prompt_id = gen.submit(workflow=WORKFLOW, parameters={
                "VIDEO_FILENAME": rel,
                "RESOLUTION": resolution,
            })
            gen.wait_for_completion(prompt_id)
            gen.download_output(prompt_id, target)
            log(f"  ✓ saved {target.name}")
            results.append({
                "rel": rel,
                "status": "done",
                "upscaled_to": str(target.relative_to(target.parents[len(target.parts) - len(Path(rel).parts) - 1])) if False else str(target),
                "prompt_id": prompt_id,
                "completed_at": datetime.now().isoformat(timespec="seconds"),
            })
        except Exception as exc:
            log(f"  ✗ failed: {exc}")
            results.append({"rel": rel, "status": "failed", "error": str(exc)})
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, help="Project ID (e.g. cend)")
    ap.add_argument("--force", action="store_true",
                    help="Re-upscale entries already marked done in state file")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--scan-dir", action="append", default=["Assets/Video"],
                    help="Folders to scan (relative to project_root or absolute). Default: Assets/Video")
    ap.add_argument("--seq-w", type=int, default=1920)
    ap.add_argument("--seq-h", type=int, default=1080)
    ap.add_argument("--resolution", default=DEFAULT_RESOLUTION,
                    help=f"SOUTS RESOLUTION parameter (default: {DEFAULT_RESOLUTION})")
    args = ap.parse_args()

    root = project_root(args.project)
    if not root.exists():
        err(f"project root does not exist: {root}")

    state_path, prev_state = load_state(args.project)
    candidates = gather_candidates(
        root, (args.seq_w, args.seq_h),
        [Path(d) for d in args.scan_dir],
        prev_state, args.force,
    )

    print()
    print("╔" + "═" * 68 + "╗")
    print(f"║  UPSCALE  ·  {args.project}  ·  {WORKFLOW}".ljust(69) + "║")
    print(f"║  eligible: {len(candidates)}  ·  resolution: {args.resolution}".ljust(69) + "║")
    if args.dry_run:
        print("║  MODE: DRY-RUN".ljust(69) + "║")
    print("╚" + "═" * 68 + "╝")

    if not candidates:
        print("\n  (no sub-resolution clips found — nothing to do)")
        return

    results = run_batch(candidates, args.resolution, args.dry_run)

    if not args.dry_run:
        for r in results:
            prev_state[r["rel"]] = r
        save_state(state_path, prev_state)

    done = sum(1 for r in results if r["status"] == "done")
    failed = sum(1 for r in results if r["status"] == "failed")
    print()
    print("─" * 70)
    print(f"  Totals: done={done}  failed={failed}")
    if not args.dry_run:
        print(f"  State: {state_path}")
        print("\nNext: Claude relinks each project item + rescales timeline instances via MCP.")


if __name__ == "__main__":
    main()
