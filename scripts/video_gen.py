#!/usr/bin/env python3
"""
video_gen.py — Thin Python wrapper for the SOUTS (vapai.studio) video generation API.

The SOUTS platform is an internal ComfyUI wrapper running open-source video models
(LTX 2.3, WAN, Qwen, Flux, etc). This module exposes a clean Python interface for
the endpoints we care about:

  - list available workflows
  - get parameter schema for a workflow
  - upload a reference image (for image-to-video workflows)
  - submit a video job
  - poll until completion
  - download the resulting MP4

Workflows relevant to CEND (2026-04-10):
  LTX23_T2V_Basic        text-to-video
  LTX23_I2V_Basic        image-to-video (first frame only)
  LTX23_FL2V_Injection   first + last frame → video (great for continuity)
  LTX23_FML2V_Injection  first + middle + last frame → video
  LTX23_I2V_Audio        i2v with audio driving
  LTX23_T2V_Basic        t2v
  WANI2V                 WAN image-to-video (alternative model)
  WanMove                WAN movement variant

Usage:
    from video_gen import SoutsVideoGen

    gen = SoutsVideoGen()
    prompt_id = gen.submit(
        workflow="LTX23_T2V_Basic",
        parameters={
            "PROMPT": "A wide aerial shot of a cargo ship at sea, cinematic",
            "WIDTH": 1280, "HEIGHT": 720, "FPS": 24, "LENGTH": 97,
        },
    )
    gen.wait_for_completion(prompt_id)
    gen.download_output(prompt_id, "output.mp4")

High-level helper:
    gen.generate(
        workflow="LTX23_T2V_Basic",
        parameters={...},
        output_path="/path/to/result.mp4",
    )

Credentials are loaded from Feedback web/config.json → `souts_api`:
    {
      "souts_api": {
        "api_base": "https://vapai-plataforma-backend-4daa799bd90b.herokuapp.com/api",
        "comfy_base": "https://comfy.vapai.studio",
        "api_key": "sout_...",
        "user_id": "..."
      }
    }

Can also be driven from the CLI:
    python3 video_gen.py list-workflows
    python3 video_gen.py workflow-params LTX23_I2V_Basic
    python3 video_gen.py t2v --prompt "cinematic aerial cargo ship" --output out.mp4
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Optional


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent                          # Feedback web/
PUBLIC_CONFIG = REPO_ROOT / "config.json"
LOCAL_CONFIG = REPO_ROOT / "config.local.json"


def load_merged_config():
    """Load Feedback web/config.json and merge config.local.json on top.

    Split rationale: config.json is public (served by GitHub Pages so the
    frontend can read site_url + GAS endpoint + brand). config.local.json
    is gitignored and holds secrets (API keys) + absolute paths that shouldn't
    leak (project_roots).
    """
    merged = {}
    if PUBLIC_CONFIG.exists():
        with open(PUBLIC_CONFIG) as f:
            merged = json.load(f)
    if LOCAL_CONFIG.exists():
        with open(LOCAL_CONFIG) as f:
            local = json.load(f)
        # shallow merge, local wins
        for k, v in local.items():
            merged[k] = v
    return merged


# ---------------------------------------------------------------------------
# Tiny HTTP helpers (stdlib-only to avoid pulling a new dep)
# ---------------------------------------------------------------------------

# The ComfyUI server sits behind a WAF (Cloudflare) that returns 403 to the
# default `Python-urllib/*` User-Agent. Any realistic UA works. We standardize
# on a generic one so both the backend API and the ComfyUI downloads go
# through the same path.
_DEFAULT_UA = "SoutsVideoGen/1.0 (+https://app.vapai.studio; python)"


def _http_request(method, url, headers=None, data=None, timeout=120):
    """Minimal wrapper on urllib. Returns (status_code, parsed_json_or_bytes)."""
    h = {"User-Agent": _DEFAULT_UA}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, method=method, headers=h)
    if data is not None and not isinstance(data, (bytes, bytearray)):
        data = json.dumps(data).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
            status = resp.getcode()
            body = resp.read()
            ctype = resp.headers.get("Content-Type", "")
            if "application/json" in ctype:
                return status, json.loads(body.decode("utf-8"))
            return status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(body)
        except Exception:
            pass
        return e.code, body


# ---------------------------------------------------------------------------
# Main client
# ---------------------------------------------------------------------------

class SoutsVideoGen:
    def __init__(self, config_path: Optional[Path] = None, quiet: bool = False):
        self.quiet = quiet
        if config_path is not None:
            with open(Path(config_path).expanduser()) as f:
                cfg = json.load(f)
        else:
            cfg = load_merged_config()
        api_cfg = cfg.get("souts_api") or {}
        missing = [k for k in ("api_base", "comfy_base", "api_key") if not api_cfg.get(k)]
        if missing:
            raise ValueError(
                f"Missing SOUTS API config keys {missing}. "
                f"Expected `souts_api` block inside config.local.json (with api_base, "
                f"comfy_base, api_key, user_id). See config.local.example.json for template."
            )
        self.api_base = api_cfg["api_base"].rstrip("/")
        self.comfy_base = api_cfg["comfy_base"].rstrip("/")
        self.api_key = api_cfg["api_key"]
        self.user_id = api_cfg.get("user_id")

    def _log(self, msg):
        if not self.quiet:
            print(f"  {msg}", flush=True)

    def _headers(self):
        return {"X-API-Key": self.api_key}

    # ----- workflows ----------------------------------------------------------

    def list_workflows(self) -> dict:
        """Return the dict {workflow_name: description} of available workflows."""
        status, body = _http_request("GET", f"{self.api_base}/comfyui/workflows",
                                     headers=self._headers())
        if status != 200 or not body.get("success"):
            raise RuntimeError(f"list_workflows failed: HTTP {status} {body}")
        return body.get("workflows", {})

    def get_workflow_params(self, workflow_name: str) -> list:
        """Return the parameter name list for a given workflow."""
        url = f"{self.api_base}/comfyui/workflows/{workflow_name}/parameters"
        status, body = _http_request("GET", url, headers=self._headers())
        if status != 200 or not body.get("success"):
            raise RuntimeError(f"get_workflow_params({workflow_name}) failed: HTTP {status} {body}")
        return body.get("parameters", [])

    # ----- image upload (for I2V workflows) -----------------------------------

    def upload_image(self, image_path: Path) -> str:
        """
        Upload a reference image (for FIRST_FRAME_FILENAME / MIDDLE_FRAME_FILENAME /
        LAST_FRAME_FILENAME params). Returns the filename the backend assigns,
        which is what you pass to the workflow parameters.

        Uses multipart/form-data via stdlib (urllib doesn't do multipart natively,
        so we build the body by hand).
        """
        image_path = Path(image_path).expanduser().resolve()
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        boundary = f"----sout-boundary-{int(time.time() * 1000)}"
        filename = image_path.name
        content_type = "image/png" if filename.lower().endswith(".png") else "image/jpeg"

        with open(image_path, "rb") as f:
            file_bytes = f.read()

        body = (
            f"--{boundary}\r\n".encode()
            + f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode()
            + f"Content-Type: {content_type}\r\n\r\n".encode()
            + file_bytes
            + f"\r\n--{boundary}--\r\n".encode()
        )
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": _DEFAULT_UA,
        }
        url = (f"{self.api_base}/comfyui/upload-image"
               f"?base_url={urllib.parse.quote(self.comfy_base, safe='')}")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"upload_image failed: HTTP {e.code} {e.read().decode(errors='replace')}")
        if not data.get("success"):
            raise RuntimeError(f"upload_image: {data}")
        # The backend returns the assigned filename — extract it
        return data.get("filename") or data.get("name") or filename

    # ----- submit / poll / download ------------------------------------------

    def submit(self, workflow: str, parameters: dict,
               client_id: Optional[str] = None) -> str:
        """Submit a workflow and return the prompt_id."""
        payload = {
            "workflow_name": workflow,
            "parameters": parameters,
            "client_id": client_id or f"souts-cli-{int(time.time())}",
            "base_url": self.comfy_base,
        }
        self._log(f"Submit → {workflow}")
        status, body = _http_request(
            "POST",
            f"{self.api_base}/comfyui/submit-workflow",
            headers=self._headers(),
            data=payload,
        )
        if status != 200 or not body.get("success"):
            raise RuntimeError(f"submit failed: HTTP {status} {body}")
        prompt_id = body.get("prompt_id")
        self._log(f"✓ prompt_id: {prompt_id}")
        return prompt_id

    def get_history(self, prompt_id: str) -> dict:
        """Return the raw history dict for a prompt_id (may be empty while running)."""
        url = (f"{self.api_base}/comfyui/history/{prompt_id}"
               f"?base_url={urllib.parse.quote(self.comfy_base, safe='')}")
        status, body = _http_request("GET", url, headers=self._headers())
        if status != 200:
            raise RuntimeError(f"get_history failed: HTTP {status} {body}")
        return body.get("history") or {}

    # ----- cancel / queue management -----------------------------------------
    #
    # The SOUTS backend doesn't expose a cancel endpoint for ComfyUI jobs, but
    # the ComfyUI server itself does. We hit it directly at `comfy_base`.
    #
    #  - interrupt()               → stop whatever is currently running
    #  - delete_from_queue(pid)    → remove a pending job from the queue
    #  - get_queue()               → list running + pending jobs
    #
    # Use these when a job is stuck or when you submitted something wrong.

    def _comfy_request(self, method, path, data=None, timeout=60):
        """Call the ComfyUI server directly (bypasses the backend wrapper)."""
        h = {"User-Agent": _DEFAULT_UA, "X-API-Key": self.api_key}
        req = urllib.request.Request(f"{self.comfy_base}{path}", method=method, headers=h)
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            req.add_header("Content-Type", "application/json")
            return urllib.request.urlopen(req, data=body, timeout=timeout)
        return urllib.request.urlopen(req, timeout=timeout)

    def get_queue(self) -> dict:
        """Return {'queue_running': [...], 'queue_pending': [...]}. Each entry is
        [priority, prompt_id, workflow_dict]."""
        with self._comfy_request("GET", "/queue") as resp:
            return json.loads(resp.read().decode())

    def interrupt(self) -> None:
        """Stop the job that's currently running in ComfyUI."""
        self._log("Interrupt → ComfyUI")
        with self._comfy_request("POST", "/interrupt") as resp:
            pass

    def delete_from_queue(self, prompt_id: str) -> None:
        """Remove a pending job from the ComfyUI queue (does not affect running)."""
        self._log(f"Delete from queue → {prompt_id}")
        with self._comfy_request("POST", "/queue", data={"delete": [prompt_id]}):
            pass

    def cancel(self, prompt_id: Optional[str] = None) -> dict:
        """Best-effort cancel. Removes the prompt from the pending queue (if
        queued) and interrupts the worker (if it's the one running). Returns
        the queue state after the operation for verification.
        """
        if prompt_id:
            try:
                self.delete_from_queue(prompt_id)
            except Exception as e:
                self._log(f"delete_from_queue failed: {e}")
        try:
            self.interrupt()
        except Exception as e:
            self._log(f"interrupt failed: {e}")
        return self.get_queue()

    def wait_for_completion(self, prompt_id: str,
                            poll_interval: int = 10,
                            timeout: int = 1800) -> dict:
        """
        Poll get_history until the job has outputs (or fails / times out).
        Returns the entry corresponding to prompt_id within the history dict.
        """
        deadline = time.time() + timeout
        last_log = 0
        while time.time() < deadline:
            history = self.get_history(prompt_id)
            entry = history.get(prompt_id) if history else None
            if entry:
                status = entry.get("status") or {}
                outputs = entry.get("outputs")
                status_str = status.get("status_str") or "running"
                completed = status.get("completed")
                if outputs or completed:
                    self._log(f"✓ Completed ({status_str})")
                    return entry
                if status_str == "error":
                    raise RuntimeError(f"Job failed: {status}")
                if time.time() - last_log > 15:
                    self._log(f"…{status_str}")
                    last_log = time.time()
            else:
                if time.time() - last_log > 15:
                    self._log("…queued")
                    last_log = time.time()
            time.sleep(poll_interval)
        raise TimeoutError(f"Job {prompt_id} did not complete within {timeout}s")

    def find_video_in_outputs(self, entry: dict) -> Optional[dict]:
        """
        ComfyUI outputs are nested per-node. Find the first node that produced a
        video/gif/mp4 file and return its file descriptor {filename, subfolder, type}.
        """
        outputs = entry.get("outputs") or {}
        # Preferred output nodes carry `gifs` / `videos` / `images` arrays.
        for node_id, node_out in outputs.items():
            for key in ("gifs", "videos", "images"):
                files = node_out.get(key)
                if files:
                    f = files[0]
                    if isinstance(f, dict) and f.get("filename"):
                        return f
        return None

    def build_comfyui_download_url(self, file_desc: dict) -> str:
        """Given a {filename, subfolder, type} descriptor, build the /api/view URL."""
        params = {
            "filename": file_desc["filename"],
            "type": file_desc.get("type", "output"),
        }
        if file_desc.get("subfolder"):
            params["subfolder"] = file_desc["subfolder"]
        qs = urllib.parse.urlencode(params)
        return f"{self.comfy_base}/api/view?{qs}"

    def download_file(self, url: str, output_path: Path):
        # Atomic-ish write: download to <name>.part, rename on success.
        # Prevents leaving truncated files at the target path if the process
        # is killed mid-download (which would otherwise be picked up as
        # "already exists" by an idempotent runner and skipped on retry).
        output_path = Path(output_path).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = output_path.with_suffix(output_path.suffix + ".part")
        self._log(f"Download → {output_path}")
        req = urllib.request.Request(url, headers={
            "X-API-Key": self.api_key,
            "User-Agent": _DEFAULT_UA,
        })
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                with open(tmp_path, "wb") as f:
                    chunk_size = 256 * 1024
                    total = 0
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        total += len(chunk)
            tmp_path.replace(output_path)  # atomic rename within same FS
        except BaseException:
            # Best-effort cleanup on any failure / interrupt
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass
            raise
        size_mb = total / (1024 * 1024)
        self._log(f"✓ Saved {size_mb:.1f} MB")

    def download_output(self, prompt_id: str, output_path: Path) -> Path:
        """Find the video output in the history and download it."""
        history = self.get_history(prompt_id)
        entry = history.get(prompt_id) if history else None
        if not entry:
            raise RuntimeError(f"No history for {prompt_id}; has it completed?")
        file_desc = self.find_video_in_outputs(entry)
        if not file_desc:
            raise RuntimeError(f"No video output in history entry for {prompt_id}. "
                               f"Raw entry: {json.dumps(entry)[:800]}")
        url = self.build_comfyui_download_url(file_desc)
        self.download_file(url, output_path)
        return Path(output_path).resolve()

    # ----- high-level helper -------------------------------------------------

    def generate(self, workflow: str, parameters: dict, output_path: Path,
                 poll_interval: int = 10, timeout: int = 1800) -> Path:
        """Submit → wait → download. One-shot helper."""
        prompt_id = self.submit(workflow, parameters)
        entry = self.wait_for_completion(prompt_id, poll_interval=poll_interval, timeout=timeout)
        file_desc = self.find_video_in_outputs(entry)
        if not file_desc:
            raise RuntimeError(f"No video output for {prompt_id}. Entry: {json.dumps(entry)[:500]}")
        url = self.build_comfyui_download_url(file_desc)
        self.download_file(url, output_path)
        return Path(output_path).resolve()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cmd_list_workflows(args):
    gen = SoutsVideoGen()
    wfs = gen.list_workflows()
    for name, desc in sorted(wfs.items()):
        print(f"  {name:40s}  {desc}")


def _cmd_workflow_params(args):
    gen = SoutsVideoGen()
    params = gen.get_workflow_params(args.workflow)
    print(json.dumps(params, indent=2))


def _cmd_t2v(args):
    gen = SoutsVideoGen()
    parameters = {
        "PROMPT": args.prompt,
        "WIDTH": args.width, "HEIGHT": args.height,
        "FPS": args.fps, "LENGTH": args.length,
    }
    gen.generate(args.workflow, parameters, args.output,
                 poll_interval=args.poll, timeout=args.timeout)
    print(f"Saved: {args.output}")


def _cmd_get_history(args):
    gen = SoutsVideoGen()
    history = gen.get_history(args.prompt_id)
    print(json.dumps(history, indent=2)[:4000])


def _cmd_wait_and_download(args):
    gen = SoutsVideoGen()
    gen.wait_for_completion(args.prompt_id, poll_interval=args.poll, timeout=args.timeout)
    gen.download_output(args.prompt_id, args.output)
    print(f"Saved: {args.output}")


def _cmd_queue(args):
    gen = SoutsVideoGen()
    q = gen.get_queue()
    running = q.get("queue_running", [])
    pending = q.get("queue_pending", [])
    print(f"running: {len(running)}   pending: {len(pending)}")
    for r in running:
        print(f"  [running] prompt_id={r[1]}")
    for r in pending:
        print(f"  [pending] prompt_id={r[1]}")


def _cmd_cancel(args):
    gen = SoutsVideoGen()
    q = gen.cancel(args.prompt_id)
    print(f"After cancel → running: {len(q.get('queue_running', []))}  "
          f"pending: {len(q.get('queue_pending', []))}")


def main():
    ap = argparse.ArgumentParser(description="SOUTS / Vapai Studio video generation client.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-workflows").set_defaults(func=_cmd_list_workflows)

    p = sub.add_parser("workflow-params")
    p.add_argument("workflow")
    p.set_defaults(func=_cmd_workflow_params)

    p = sub.add_parser("t2v", help="Text-to-video generation (one-shot)")
    p.add_argument("--prompt", required=True)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--workflow", default="LTX23_T2V_Basic")
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=720)
    p.add_argument("--fps", type=int, default=24)
    p.add_argument("--length", type=int, default=97, help="Number of frames (97 ≈ 4s at 24fps)")
    p.add_argument("--poll", type=int, default=10)
    p.add_argument("--timeout", type=int, default=1800)
    p.set_defaults(func=_cmd_t2v)

    p = sub.add_parser("get-history", help="Dump raw history for a prompt_id")
    p.add_argument("prompt_id")
    p.set_defaults(func=_cmd_get_history)

    p = sub.add_parser("wait-and-download",
                       help="Wait for a pre-submitted prompt_id and download the result")
    p.add_argument("prompt_id")
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--poll", type=int, default=10)
    p.add_argument("--timeout", type=int, default=1800)
    p.set_defaults(func=_cmd_wait_and_download)

    p = sub.add_parser("queue", help="Show the current ComfyUI queue state")
    p.set_defaults(func=_cmd_queue)

    p = sub.add_parser("cancel",
                       help="Cancel a job: removes it from the pending queue (if "
                            "queued) and interrupts the running worker. "
                            "Without --prompt-id, only interrupts the running one.")
    p.add_argument("--prompt-id", default=None)
    p.set_defaults(func=_cmd_cancel)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
