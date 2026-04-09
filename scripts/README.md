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
