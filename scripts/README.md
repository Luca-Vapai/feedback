# Scripts — SideOutSticks Reviews tooling

Automated publishing tools for the feedback web. One command renders → Drive → YouTube → config → transcript → review link.

---

## What `publish_version.py` does

Given a rendered MP4, the script runs the following pipeline end-to-end:

1. **Rename** the file to the naming convention: `CEND_[piece]_v[N]_[YYYYMMDD]_[HHMM].mp4`
2. **Copy to Drive**: `CEND Nuevo/Exports/[Piece folder]/`
3. **Copy locally**: `Cend/Exports/[Piece folder]/`
4. **Upload to YouTube** as unlisted
5. **Delete the previous version's YouTube video** (so the account doesn't fill up with old versions)
6. **Generate a word-level transcript** with Whisper
7. **Update `projects/[id]/config.json`** by appending the new version entry
8. **Print the review link** and the next git commands

**End result:** one CLI call replaces ~10 manual steps.

---

## One-time setup

You need to do this once. After that, every publish is a single command.

### 1. Install Python dependencies

The main project already has a `.venv` from previous Whisper work. Use it:

```bash
source /Users/luca/Downloads/Cend/.venv/bin/activate
pip install -r "/Users/luca/Downloads/Cend/Feedback web/scripts/requirements.txt"
```

### 2. Create OAuth credentials for the YouTube API

YouTube requires OAuth. This is a one-time browser flow.

#### a) Create a Google Cloud project

1. Go to https://console.cloud.google.com/
2. Top-left project dropdown → **New Project** → name it `souts-reviews` (or any name) → Create.
3. Make sure the new project is selected in the top-left dropdown.

#### b) Enable the YouTube Data API v3

1. Left menu → **APIs & Services** → **Library**.
2. Search for `YouTube Data API v3` → click it → **Enable**.

#### c) Configure the OAuth consent screen

1. Left menu → **APIs & Services** → **OAuth consent screen**.
2. User type: **External** → Create.
3. Fill the required fields minimally:
   - App name: `SOUTS Reviews`
   - User support email: your email
   - Developer contact: your email
4. Click Save and Continue through the Scopes step (no need to add scopes here).
5. Test users step: click **+ Add users** and add your own Google account. Save.
6. Back to dashboard.

#### d) Create OAuth client credentials

1. Left menu → **APIs & Services** → **Credentials**.
2. **+ Create Credentials** → **OAuth client ID**.
3. Application type: **Desktop app** → Name: `SOUTS Reviews CLI` → Create.
4. A popup shows your client ID + secret. Click **Download JSON**.
5. Rename the downloaded file to `client_secret.json`.
6. Move it to `Feedback web/scripts/credentials/client_secret.json`.

> **Never commit this file.** It's already listed in `scripts/.gitignore`.

### 3. First run (triggers the browser auth)

```bash
source /Users/luca/Downloads/Cend/.venv/bin/activate
python3 "/Users/luca/Downloads/Cend/Feedback web/scripts/publish_version.py" \
  --project cend \
  --piece commercial \
  --file "/path/to/any/test.mp4" \
  --dry-run
```

On the first run you'll see:
- A browser window opens asking you to sign in to Google
- You'll see a warning "Google hasn't verified this app" — click **Advanced** → **Go to SOUTS Reviews (unsafe)** → **Allow**
- Grant the YouTube permissions
- The browser says "The authentication flow has completed"

A `token.json` gets saved to `credentials/`. Future runs will use it silently. If the token ever expires, the script will auto-refresh it.

---

## Daily usage

After rendering a new version in Premiere:

```bash
source /Users/luca/Downloads/Cend/.venv/bin/activate

python3 "/Users/luca/Downloads/Cend/Feedback web/scripts/publish_version.py" \
  --project cend \
  --piece commercial \
  --file "/Users/luca/Downloads/Cend/Exports/Comercial/Comercial.mp4"
```

The script:
- Auto-increments the version from the latest in `config.json`
- Copies to Drive and locally with the correct name
- Uploads to YouTube (unlisted)
- Deletes the previous YouTube video
- Generates a transcript
- Updates `config.json`
- Prints the review link and the git commands to push

Then just `cd` into `Feedback web/` and run the printed git commands.

---

## CLI flags

| Flag | Description |
|---|---|
| `--project ID` | Project id (required). e.g. `cend` |
| `--piece ID` | Piece id (required). e.g. `commercial`, `manifesto` |
| `--file PATH` | Path to the rendered MP4 (required) |
| `--version N` | Override version number (default: auto-increment from config) |
| `--keep-old-yt` | Do NOT delete the previous YouTube video (useful to preserve history) |
| `--skip-transcript` | Skip Whisper transcript generation (use the same transcript as before) |
| `--dry-run` | Print what would happen without touching YouTube or config.json |

---

## Troubleshooting

**"OAuth client secret not found"** — You haven't placed `client_secret.json` in `credentials/` yet. See step 2.d above.

**"Google Auth Flow error" or browser doesn't open** — Make sure you're using a desktop app type credential (not web app). The Flow uses a local redirect on `http://localhost`.

**"quota exceeded"** — YouTube Data API has a default quota of 10,000 units/day. An upload costs ~1,600 units. So up to ~6 uploads per day. Delete operations are 50 units. If you hit the limit, wait 24 hours or request a quota increase in the Google Cloud Console.

**"The uploaded video was rejected"** — YouTube may flag certain content. Check the video manually in YouTube Studio.

**YouTube playback on the web shows "video unavailable"** — the video might still be processing (YouTube takes 1-5 minutes after upload). Refresh the review page after a couple of minutes.

---

## How the script integrates with the feedback web

```
[Render MP4]
      │
      ▼
  publish_version.py
      │
      ├─► Copy to Drive (CEND Nuevo/Exports/...)
      ├─► Copy locally (Cend/Exports/...)
      ├─► Upload to YouTube (unlisted) → get new video ID
      ├─► Delete previous YouTube video
      ├─► Whisper transcript → projects/[id]/transcripts/[piece]-v[N].json
      └─► Append version entry to projects/[id]/config.json
              │
              ▼
     (manual) git commit + push
              │
              ▼
     GitHub Pages redeploys
              │
              ▼
     Review link is live
```

---

## File structure

```
scripts/
├── README.md                    ← this file
├── publish_version.py           ← the main CLI
├── requirements.txt             ← Python dependencies
├── .gitignore                   ← keeps credentials out of git
└── credentials/                 ← local only, never committed
    ├── client_secret.json       ← you create this (step 2.d)
    └── token.json               ← auto-generated on first run
```

---

## Known issues + pending robustness work

### 1. Generation batches can stall silently (TODO: watchdog)

Observed on cend v3 (2026-04-15): a single `batch_video.py` job sat inside the SOUTS/Comfy queue for ~40 min without progressing. The HTTP poll (`/history/<prompt_id>`) kept returning the same response, so the batch runner couldn't tell the job from one that's legitimately slow. Luca had to interrupt it manually from the Comfy UI.

**Required fix** (documented; not yet implemented):

- In addition to HTTP polling, open a **WebSocket connection** to Comfy (`wss://<comfy_base>/ws?clientId=<uuid>`) and subscribe to the `progress` events it emits per node execution.
- Maintain a per-job `last_progress_at` timestamp. If **5 minutes** pass without any progress event, treat the job as stuck.
- Call `POST /interrupt` on the server to kill the **whole workflow** for that prompt_id (not a single node).
- Mark the item in the state file as `interrupted_stuck` with the dead prompt_id preserved for debugging, then resubmit with a fresh prompt_id.
- Don't block the rest of the batch — the stuck item is processed independently while the others continue.
- Cap retries per item at 2 (config); after that, mark `permanently_stuck` and skip.

See memory `feedback_comfy_watchdog.md` for the full design.

### 2. No GPU preflight check (TODO)

A batch of 8 jobs on cend v3 took 38 min because the SOUTS GPU was already heavily loaded by other users' traffic. The runner had no way to know before submitting.

**Required fix** (documented; not yet implemented):

- Before calling `submit` on the first item of a batch, query a SOUTS/Comfy system stats endpoint (`/system_stats` or equivalent) to read GPU utilization, queue depth, workers alive.
- If the GPU is >80% saturated or the queue has >N items ahead, abort with an actionable message (`"GPU saturated (92%), 35 jobs ahead — delay or pass --force"`).
- Expose `--force` to skip the check in urgent cases, `--wait` to re-check every N minutes instead of aborting.

See memory `feedback_gpu_preflight.md`.

### Priority

Both items above matter for unattended automation (the generic `feedback-loop` CLI we're extracting this tooling into). For the cend-only pipeline they're "nice to have" — Luca can intervene manually when something stalls. In the portable system they are blocking for running a loop without supervision.

---

## Closing-the-montage routine (QA gate + 3 steps)

When the editor signals that manual editing is done ("ya acomodé todo", "listo el montaje"), execute this sequence every time:

**Step 0 — QA gate visual (MANDATORY, blocking)**

Before touching the render, validate each QA item in the current `Guión de montaje v<N>.md`:

- `mcp__premiere-pro__export_frame` at each timecode into `/tmp/qa_v<N>/<piece>_<tc>.png`.
- Read each PNG (multimodal) and evaluate the textual condition ("no haya watermark", "clip a pantalla completa", "subtítulo aparezca cuando dice X", etc.).
- Build a PASS/FAIL table.
- If any FAIL: **stop**. Show the user the failing frames + the condition + likely root cause. Offer three options: fix automatic, fix manual then retry, or continue anyway (tracked in bitácora).
- Only advance to Steps 1-3 if the gate passes (or the user explicitly chose "continue anyway").

Known bug: `export_frame` may return ~t=0 content right after project changes. Workaround: always `save_project` first; retry after save if the first batch looks stale.

**Step 1 — Analyze sequences**

`mcp__premiere-pro__list_sequence_tracks` on each piece. Map against the previous mental model and capture editor-driven changes (music added, excerpts split, SELs moved between tracks, manual trims). Update the project bitácora so the next iteration starts from the real timeline state.

**Step 2 — Export + publish each piece**

`export_sequence` to `Exports/<Piece>/<canonical_name>.mp4`, then `publish_version.py --project <id> --piece <piece> --file <render>`. The script handles rename, Drive (history retained), YouTube unlisted (previous version deleted, see `feedback_drive_vs_youtube_versioning` memory), Whisper transcript, and `config.json` update. Then `git commit + push` the feedback-web repo.

**Step 3 — Update project timecode**

Copy each `Feedback web/projects/<id>/transcripts/<piece>-v<N>.json` to `Documentación/Transcripts/<piece>_v<N>.json` in the project root. This is the canonical word-level timecode for the new version, used by Claude in the next round to map reviewer comments to exact frames. The editor may have shifted VO clips during the montage, so the transcript must come from the rendered MP4, not from any pre-edit master.

---

Pattern memories: `feedback_close_montage_routine.md`, `feedback_qa_gate_pre_render.md`, `feedback_brand_vocabulary.md`. Implementation in the portable CLI lives in `feedback-loop/lib/loop.py::tramo_render` + `lib/qa.py` + `lib/transcribe.py`.

---

## Brand vocabulary (fix Whisper mis-hearings automatically)

Whisper transcribes phonetically and maps uncommon brand names to common English words (`CEND` → `send`, `Souts` → `sauce`). The fix is a per-project dict of substitutions applied right after Whisper runs, before the JSON is written.

**Config:** `projects/<project_id>/brand_vocabulary.json` — a flat dict `{"wrong": "right"}`. Example for cend:

```json
{
  "send": "CEND",
  "Send": "CEND",
  "sent": "CEND",
  "Sent": "CEND"
}
```

Keys are exact matches on the bare word token; trailing punctuation (`. , ; : ! ?`) is preserved automatically, so you only list the bare form. `publish_version.py::generate_transcript` loads it via `load_brand_vocabulary(project_id)` and applies it with `apply_brand_vocabulary(words, vocab)`. Missing file → no-op.

**Discovery workflow:**

1. After a feedback round, grep comments where element=Subtitles and the reported text differs from the script text.
2. If the difference is a phonetic match (`CEND` ↔ `send`), add the entry to the dict.
3. Commit. Next round's Whisper output is clean for that term.

Tracked on cend since v5 (2026-04-15) after 3 consecutive `send` → `CEND` fixes.
