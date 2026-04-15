#!/usr/bin/env python3
"""
publish_version.py — Publish a new version of a piece.

End-to-end flow:
  1. Takes a rendered MP4 file (any name).
  2. Renames it following the project naming convention.
  3. Copies to Drive (CEND Nuevo/Exports/[Piece]/).
  4. Copies to the local Exports folder.
  5. Uploads to YouTube as UNLISTED.
  6. Deletes the previous YouTube video for this piece (unless --keep-old-yt).
  7. Generates a word-level transcript with Whisper.
  8. Appends the new version to projects/[id]/config.json.
  9. Prints the review link and the next git steps.

Usage:
  python3 publish_version.py --project cend --piece commercial --file /path/to/render.mp4
  python3 publish_version.py --project cend --piece manifesto --file ~/Downloads/Cend/Exports/Manifiesto/Manifiesto.mp4 --version 1

Flags:
  --project          Project ID (e.g. cend)  [required]
  --piece            Piece ID (e.g. commercial, manifesto)  [required]
  --file             Path to the rendered MP4 file  [required]
  --version N        Override version number (default: auto-increment from config)
  --keep-old-yt      Do NOT delete the previous YouTube video
  --skip-transcript  Skip Whisper transcript generation (useful if script didn't change)
  --dry-run          Print what would happen without touching YouTube or config.json

First-time setup: see scripts/README.md
"""

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# --- Configuration -----------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent                   # Feedback web/
CREDS_DIR = SCRIPT_DIR / 'credentials'
TOKEN_PATH = CREDS_DIR / 'token.json'
CLIENT_SECRET_PATH = CREDS_DIR / 'client_secret.json'

# YouTube API scope: full manage access (upload + delete)
SCOPES = ['https://www.googleapis.com/auth/youtube']


def project_root(project_id):
    """Return the root folder of a project, as defined in the global config.

    The global config (Feedback web/config.json) has a `project_roots` dict
    mapping project_id → absolute path. This is the single source of truth
    for "where does project X live on disk", so the same script works whether
    the project is on a local drive, on Google Drive Desktop, or anywhere else.
    """
    cfg, _ = load_global_config()
    roots = cfg.get('project_roots', {})
    if project_id not in roots:
        err(f"project_roots[{project_id!r}] not set in {REPO_ROOT / 'config.json'}")
    return Path(roots[project_id]).expanduser()


# --- Utilities ---------------------------------------------------------------------

def err(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def log(msg, prefix="  "):
    print(f"{prefix}{msg}", flush=True)


def load_global_config():
    """Load config.json (public) + merge config.local.json (gitignored) on top.

    The public file holds what GitHub Pages needs to serve the frontend
    (site_url, GAS endpoint, brand). The local file holds secrets and absolute
    paths (project_roots, souts_api key). Local wins on conflict.
    """
    public_path = REPO_ROOT / 'config.json'
    local_path = REPO_ROOT / 'config.local.json'
    if not public_path.exists():
        err(f"config.json not found at {public_path}")
    with open(public_path) as f:
        merged = json.load(f)
    if local_path.exists():
        with open(local_path) as f:
            local = json.load(f)
        for k, v in local.items():
            merged[k] = v
    # We return the public path because that's what users mostly edit; scripts
    # that need to know the local path should import it directly.
    return merged, public_path


def load_project_config(project_id):
    path = REPO_ROOT / 'projects' / project_id / 'config.json'
    if not path.exists():
        err(f"Project config not found: {path}")
    with open(path) as f:
        return json.load(f), path


def save_project_config(config, path):
    with open(path, 'w') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write('\n')


def find_piece(config, piece_id):
    for p in config.get('pieces', []):
        if p['id'] == piece_id:
            return p
    return None


def get_next_version(piece):
    versions = piece.get('versions', [])
    if not versions:
        return 0
    return max(v['version'] for v in versions) + 1


def latest_version_entry(piece):
    versions = piece.get('versions', [])
    if not versions:
        return None
    return max(versions, key=lambda v: v['version'])


def make_target_filename(project_id, piece_id, version, dt):
    return f"{project_id.upper()}_{piece_id}_v{version}_{dt.strftime('%Y%m%d_%H%M')}.mp4"


def probe_duration(path):
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'csv=p=0', str(path)],
            capture_output=True, text=True, check=True
        )
        return round(float(result.stdout.strip()), 2)
    except Exception as e:
        log(f"Warning: could not read duration ({e})")
        return 0


# --- YouTube ----------------------------------------------------------------------

def get_youtube_service():
    """Load or refresh OAuth credentials and return a YouTube API client."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        err("Google API libraries not installed. "
            "Run: pip install -r scripts/requirements.txt")

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log("Refreshing OAuth token…")
            creds.refresh(Request())
        else:
            if not CLIENT_SECRET_PATH.exists():
                err(f"OAuth client secret not found at {CLIENT_SECRET_PATH}\n"
                    "See scripts/README.md for one-time setup instructions.")
            log("Starting OAuth flow (a browser window will open)…")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CLIENT_SECRET_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(TOKEN_PATH, 'w') as f:
            f.write(creds.to_json())

    return build('youtube', 'v3', credentials=creds)


def upload_youtube(service, file_path, title, description):
    from googleapiclient.http import MediaFileUpload

    body = {
        'snippet': {
            'title': title,
            'description': description,
            'categoryId': '22',  # People & Blogs
        },
        'status': {
            'privacyStatus': 'unlisted',
            'selfDeclaredMadeForKids': False,
        }
    }
    media = MediaFileUpload(str(file_path), chunksize=8 * 1024 * 1024, resumable=True)
    request = service.videos().insert(
        part='snippet,status', body=body, media_body=media
    )

    last_pct = -1
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            if pct != last_pct:
                log(f"Upload progress: {pct}%")
                last_pct = pct

    return response['id']


def delete_youtube(service, video_id):
    from googleapiclient.errors import HttpError
    try:
        service.videos().delete(id=video_id).execute()
        return True
    except HttpError as e:
        log(f"Warning: could not delete YouTube video {video_id}: {e}")
        return False


# --- Transcript ------------------------------------------------------------------

def load_brand_vocabulary(project_id):
    """Load optional per-project Whisper substitutions.

    Looks for `Feedback web/projects/<project_id>/brand_vocabulary.json` — a
    flat dict of `{"whisper_output": "canonical_form"}`. Used to fix brand
    names Whisper doesn't know (e.g. `{"send": "CEND", "Send": "CEND"}`).

    Returns {} if the file doesn't exist."""
    path = REPO_ROOT / "projects" / project_id / "brand_vocabulary.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception as e:
        log(f"Warning: brand_vocabulary.json unreadable ({e}); skipping")
        return {}


def apply_brand_vocabulary(words, vocab):
    """Rewrite each word's text token using the substitution dict.

    Matches are on the bare token (stripped of surrounding whitespace); any
    trailing punctuation (`. , ; :`) is preserved. Returns the number of
    tokens actually substituted."""
    if not vocab:
        return 0
    changes = 0
    trailing_punct = set(".,;:!?")
    for w in words:
        tok = w["word"]
        tail = ""
        while tok and tok[-1] in trailing_punct:
            tail = tok[-1] + tail
            tok = tok[:-1]
        if tok in vocab:
            w["word"] = vocab[tok] + tail
            changes += 1
    return changes


def generate_transcript(source_path, output_path, project_id=None):
    """Run Whisper with word-level timestamps and save the flat word list.

    If `project_id` is given, apply the project's brand_vocabulary.json (if
    present) to the transcribed words before writing — fixes brand names and
    other tokens Whisper consistently mis-hears."""
    try:
        import whisper
    except ImportError:
        err("openai-whisper not installed. Run: pip install -r scripts/requirements.txt")

    log("Loading Whisper model (base)…")
    model = whisper.load_model('base')
    log("Transcribing…")
    result = model.transcribe(
        str(source_path), word_timestamps=True, language='en'
    )

    words = []
    for seg in result['segments']:
        for w in seg.get('words', []):
            words.append({
                'word': w['word'].strip(),
                'start': round(w['start'], 2),
                'end': round(w['end'], 2),
            })

    if project_id:
        vocab = load_brand_vocabulary(project_id)
        changes = apply_brand_vocabulary(words, vocab)
        if changes:
            log(f"Brand vocab: substituted {changes} token(s)")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(words, f, indent=2, ensure_ascii=False)
    return len(words)


# --- Main -----------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description='Publish a new version of a piece (Drive copy + YouTube upload + config update).'
    )
    ap.add_argument('--project', required=True, help='Project ID (e.g. cend)')
    ap.add_argument('--piece', required=True, help='Piece ID (e.g. commercial, manifesto)')
    ap.add_argument('--file', required=True, help='Path to the rendered MP4 file')
    ap.add_argument('--version', type=int, default=None,
                    help='Override version number (default: auto-increment)')
    ap.add_argument('--keep-old-yt', action='store_true',
                    help='Do NOT delete the previous YouTube video')
    ap.add_argument('--skip-transcript', action='store_true',
                    help='Skip Whisper transcript generation')
    ap.add_argument('--dry-run', action='store_true',
                    help='Print what would happen without touching YouTube or config.json')
    args = ap.parse_args()

    # Validate file
    src_path = Path(args.file).expanduser().resolve()
    if not src_path.exists():
        err(f"File not found: {src_path}")
    if not src_path.suffix.lower() == '.mp4':
        log(f"Warning: file does not have .mp4 extension ({src_path.suffix})")

    # Load configs
    global_config, _ = load_global_config()
    project_config, project_config_path = load_project_config(args.project)
    piece = find_piece(project_config, args.piece)
    if not piece:
        err(f"Piece '{args.piece}' not found in project '{args.project}'")

    # Determine version
    version = args.version if args.version is not None else get_next_version(piece)
    now = datetime.now()

    # Build target filename
    target_name = make_target_filename(args.project, args.piece, version, now)

    print()
    print("=" * 70)
    print(f"  PUBLISH  {args.project}/{args.piece}  v{version}")
    print("=" * 70)
    print(f"  Source:      {src_path}")
    print(f"  Target name: {target_name}")
    print(f"  Date/time:   {now.strftime('%Y-%m-%d %H:%M:%S')}")
    if args.dry_run:
        print(f"  Mode:        DRY-RUN (no YouTube, no config write)")
    print()

    # Copy to the project root (defined in global config.json under
    # `project_roots`). The project root is the single source of truth for
    # where the project lives — local drive, Google Drive, etc.
    # `folder_name` in the piece config overrides the default (useful when
    # filesystem folders use a different language than the piece name).
    folder_name = piece.get('folder_name', piece['name'])
    proj_root = project_root(args.project)
    target_dir = proj_root / 'Exports' / folder_name
    target_path = target_dir / target_name
    if not proj_root.exists():
        err(f"Project root not found: {proj_root}\n"
            "Update `project_roots` in Feedback web/config.json.")
    log(f"→ Copying to project root: {target_path}")
    if not args.dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, target_path)

    # YouTube upload
    new_yt_id = None
    if args.dry_run:
        log("→ (dry-run) would upload to YouTube as unlisted")
        new_yt_id = 'DRYRUN_YT_ID'
    else:
        log("→ Uploading to YouTube (unlisted)…")
        yt = get_youtube_service()
        title = f"{project_config['name']} — {piece['name']} v{version}"
        description = (
            f"Internal review version. Exported {now.strftime('%Y-%m-%d %H:%M')}.\n"
            f"Project: {project_config['name']} · Piece: {piece['name']} · Version: {version}"
        )
        new_yt_id = upload_youtube(yt, src_path, title, description)
        log(f"✓ YouTube ID: {new_yt_id}")

        # Delete previous YouTube video
        prev = latest_version_entry(piece)
        if prev and not args.keep_old_yt:
            old_id = prev.get('youtube_id')
            if old_id and not old_id.startswith('PENDING') and old_id != new_yt_id:
                log(f"→ Deleting previous YouTube video ({old_id})…")
                if delete_youtube(yt, old_id):
                    prev['youtube_id'] = None
                    log("✓ Previous video deleted")

    # Transcript
    transcript_rel = f"transcripts/{args.piece}-v{version}.json"
    transcript_abs = REPO_ROOT / 'projects' / args.project / transcript_rel
    if args.skip_transcript:
        log("→ (skipped) Whisper transcript")
    else:
        if not args.dry_run:
            log("→ Generating transcript with Whisper…")
            word_count = generate_transcript(src_path, transcript_abs, project_id=args.project)
            log(f"✓ Transcript: {word_count} words → {transcript_rel}")
        else:
            log(f"→ (dry-run) would generate transcript at {transcript_rel}")

    # Duration
    duration = probe_duration(src_path)

    # Build version entry + update config
    new_entry = {
        'version': version,
        'export_date': now.strftime('%Y-%m-%d %H:%M'),
        'youtube_id': new_yt_id,
        'duration_seconds': duration,
        'transcript_file': transcript_rel,
    }

    if args.dry_run:
        log(f"→ (dry-run) would append to config.json: {json.dumps(new_entry, ensure_ascii=False)}")
    else:
        piece.setdefault('versions', []).append(new_entry)
        save_project_config(project_config, project_config_path)
        log(f"✓ Updated {project_config_path.name}")

    # Next steps
    site_url = global_config.get('site_url', 'https://luca-vapai.github.io/feedback')
    review_link = f"{site_url}/piece.html?project={args.project}&piece={args.piece}&v={version}"

    print()
    print("=" * 70)
    print("  DONE")
    print("=" * 70)
    print(f"  Review link: {review_link}")
    print()
    print("  Next steps (run from repo root):")
    print(f"    git -C '{REPO_ROOT}' add .")
    print(f"    git -C '{REPO_ROOT}' commit -m 'Publish {args.project}/{args.piece} v{version}'")
    print(f"    git -C '{REPO_ROOT}' push")
    print()


if __name__ == '__main__':
    main()
