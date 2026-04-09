# SideOutSticks Reviews

A minimal static web app to collect structured, timecode-anchored feedback on video edits.

The web shows a YouTube-hosted video for each piece + version, lets reviewers leave categorized comments anchored to a specific moment (or range), and submits everything to a Google Sheet that Claude reads to generate action items for the next iteration.

> **Read [Planificación.md](./Planificación.md) for the full design rationale.**

---

## Quick start (per project)

### Prerequisites
- A GitHub account (free)
- A Google account (free) — for hosting the Sheet + Apps Script
- A YouTube account (free) — for hosting the video files

### One-time setup (done once for the whole repo, reused across all projects)

1. **Create the GitHub repo**
   - Push the contents of this `Feedback web/` folder to a new repo (e.g. `souts-reviews`).
   - Settings → Pages → Deploy from branch → `main` / root → Save.
   - Wait ~1 minute. Your site is live at `https://[username].github.io/souts-reviews/`.

2. **Set up ONE shared Google Sheet + Apps Script (for all projects)**
   - Open [`gas-endpoint.gs`](./gas-endpoint.gs) and follow the comment block at the top, step by step.
   - You'll end up with a Web App URL like `https://script.google.com/macros/s/.../exec`.
   - This same Sheet and endpoint are used by every project. Rows are disambiguated by the `project_id` column.

3. **Configure the site**
   - Edit the root [`config.json`](./config.json) (at `Feedback web/config.json`):
     - Paste the GAS URL into `google_apps_script_endpoint`.
   - Edit `projects/cend/config.json`:
     - For each version, paste the YouTube video ID (the part after `?v=`) into `youtube_id`.
   - Commit + push.

### When you cut a new version (fully automated)

1. Export the new MP4 from Premiere to `Exports/[piece folder]/` (any name).
2. Run ONE command:
   ```bash
   source /Users/luca/Downloads/Cend/.venv/bin/activate
   python3 "Feedback web/scripts/publish_version.py" \
     --project cend --piece commercial \
     --file "Exports/Comercial/Comercial.mp4"
   ```
   The script renames the file, copies it to Drive, uploads to YouTube as unlisted, deletes the previous YouTube video, generates a Whisper transcript, and updates `config.json`.
3. Commit + push (the script prints the exact commands).
4. Share the review link with reviewers.

See [`scripts/README.md`](./scripts/README.md) for the one-time OAuth setup.

---

## Adding a new project

Adding a new project does NOT require touching the Google Sheet or the Apps Script — those are shared across all projects.

1. Create a folder `projects/[id]/` with a `config.json` (use `projects/cend/config.json` as a template; do NOT include a `google_apps_script_endpoint` field, that lives in the root config).
2. Add `projects/[id]/transcripts/` with the word-level JSON for each version.
3. Add the project ID to the `PROJECTS` array near the bottom of `index.html`.
4. Commit + push.

---

## File structure

```
Feedback web/
├── index.html                 # Project selector
├── project.html               # Project home (lists pieces and versions)
├── piece.html                 # Review page (player + comment form)
├── config.json                # Global config: GAS endpoint + brand (shared by all projects)
├── README.md                  # This file
├── Planificación.md           # Design and rationale (Spanish)
├── gas-endpoint.gs            # Google Apps Script code (deploy manually, once)
├── assets/
│   ├── css/style.css
│   └── js/
│       ├── config-loader.js   # Loads project config + transcript
│       ├── player.js          # YouTube IFrame API wrapper
│       ├── transcript.js      # Phrase lookup by timecode
│       ├── comments.js        # In-memory + localStorage state
│       ├── form.js            # Comment form modal
│       ├── submit.js          # POSTs comments to GAS
│       └── piece-init.js      # Bootstraps the piece review page
└── projects/
    └── cend/
        ├── config.json
        └── transcripts/
            ├── manifesto-v0.json
            └── commercial-v0.json
```

---

## How feedback flows

1. Reviewer opens a piece review link.
2. Pauses the video at any moment, clicks "Add comment at current time" (or marks a range, or "General comment").
3. The form opens pre-populated with the current timecode and the script phrase Whisper transcribed at that moment.
4. Reviewer fills element, action, priority, and description.
5. Comment appears in the side panel. Editable/deletable until submission.
6. On "Submit feedback", all comments POST to the GAS endpoint as a single JSON payload.
7. The Apps Script appends one row per comment to the Sheet.
8. Claude (in a future session) reads the Sheet to generate action items for the next version.

---

## Sheet schema

Each row of the `feedback` tab in the Sheet:

| Column | Description |
|---|---|
| `timestamp` | When the submission arrived |
| `project_id` | e.g. `cend` |
| `piece_id` | e.g. `manifesto` |
| `version` | e.g. `0` |
| `reviewer_name` | Free text from the form |
| `comment_id` | Browser-generated UUID |
| `timecode_start` | Seconds. Empty for general comments |
| `timecode_end` | Seconds. Equal to start for point comments, larger for ranges |
| `transcript_excerpt` | The script phrase at that moment, auto-extracted |
| `element` | Music / Dialogue / Sound / Video / Editing / Graphics |
| `action` | Substitute / Improve / Modify |
| `priority` | Must-fix / Nice-to-have / Suggestion |
| `description` | Free text from the reviewer |

---

## Local development

Open `index.html` directly in a browser? **No** — `fetch()` for the JSON files won't work from `file://`. Run a local server instead:

```bash
cd "Feedback web"
python3 -m http.server 8000
# then open http://localhost:8000
```

YouTube playback works on localhost.

---

## Limitations

- Uploads to YouTube are manual (no API automation).
- Reviewers are not authenticated — anyone with the link can submit.
- No live collaboration — each reviewer sees only their own draft until submission.
- Requires internet to play the video.
- The GAS deploy step is one-time but does require ~5 manual clicks.
