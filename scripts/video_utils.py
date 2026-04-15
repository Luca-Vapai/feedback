#!/usr/bin/env python3
"""
Shared video helpers for the Cend scripts — mirrors `feedback-loop/lib/video_utils.py`.

Three pure functions: probe the native resolution, compute the Premiere
scale needed to cover the sequence, and resolve the next-version filename
per `Documentación/Nomenclatura.md`.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Tuple


_VERSION_SUFFIX_RE = re.compile(r"_v(\d+)$")


def probe_resolution(path: Path) -> Tuple[int, int]:
    """Return (width, height) via ffprobe. Raises CalledProcessError on error."""
    out = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=s=x:p=0",
            str(path),
        ],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    w, h = out.split("x")
    return int(w), int(h)


def compute_scale_pct(
    clip_wh: Tuple[int, int],
    sequence_wh: Tuple[int, int],
    safety_margin_pct: float = 0.0,
) -> float:
    """Premiere scale (%) for a clip to cover the sequence.

    Cover strategy: `max(seq_w/clip_w, seq_h/clip_h) * 100`. Works for both
    up-scale (clip < seq) and down-scale (clip > seq, post-upscale). The
    safety margin adds a relative overshoot to mask aspect-ratio mismatch
    on the edges (Cend uses 2.67% → 154% for 720p → 1080p)."""
    cw, ch = clip_wh
    sw, sh = sequence_wh
    base = max(sw / cw, sh / ch) * 100.0
    return round(base * (1.0 + safety_margin_pct / 100.0), 2)


def next_version_path(path: Path) -> Path:
    """Next-version filename per Nomenclatura.md.

    - `..._v<N>.ext` → `..._v<N+1>.ext`
    - otherwise     → `...<stem>_v2.ext`
    """
    stem = path.stem
    ext = path.suffix
    m = _VERSION_SUFFIX_RE.search(stem)
    if m:
        n = int(m.group(1))
        new_stem = stem[: m.start()] + f"_v{n + 1}"
    else:
        new_stem = stem + "_v2"
    return path.with_name(new_stem + ext)


def is_sub_resolution(clip_wh, sequence_wh) -> bool:
    cw, ch = clip_wh
    sw, sh = sequence_wh
    return cw < sw or ch < sh
