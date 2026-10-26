#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DA Sales Calls — Phase 1 pipeline
=================================
After each Zoom call (scheduled in Google Calendar), this:
  1. finds a finished local Zoom recording,
  2. reads its start time and matches it to the Google Calendar event,
  3. decides WHICH Drive folder it belongs in, by matching a keyword against
     the event title and/or the Zoom meeting name (see RULES in config.json),
  4. renames the video (+ audio) to the event's title (optionally + date),
  5. uploads it to that rule's Google Drive folder (verified by size+md5),
  6. deletes the local copy once the upload is confirmed.

ONE Google sign-in covers both jobs: Calendar (read-only) + Drive (upload).
Everything is driven by config.json (copy from config.example.json).

Routing (config "RULES"): a list of {name, keyword, drive_folder_id}. The first
rule whose keyword appears in the event title OR the Zoom meeting name wins.
An empty keyword = catch-all (put it last). A rule with no drive_folder_id yet
is inactive (ignored) until you fill it in.

Modes:
  python pipeline.py --watch          # long-running poll loop (used by the LaunchAgent)
  python pipeline.py --scan           # process every ready recording once, then exit
  python pipeline.py --once "PATH"    # process a single meeting folder (for testing)
  python pipeline.py --dry-run --scan # do everything EXCEPT rename/upload/delete
  python pipeline.py --reset-state    # forget which folders were processed/skipped
"""

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo  # type: ignore

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------
BASE = Path(__file__).resolve().parent
CONFIG_PATH = BASE / "config.json"
TOKEN_PATH = BASE / "token.json"
CREDS_PATH = BASE / "credentials.json"
STATE_PATH = BASE / "state.json"
LOG_DIR = BASE / "logs"

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",  # read events only
    "https://www.googleapis.com/auth/drive",              # upload to your folders
]
TZ = None  # tz for reading Zoom folder timestamps; None = the Mac's local timezone

# Zoom names each meeting folder: "2026-08-10 13.59.53 <topic>"
FOLDER_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2}) (\d{2})\.(\d{2})\.(\d{2}) ")
CONVERTING_GLOB = "double_click_to_convert_*.zoom"
VIDEO_GLOBS = ("video*.mp4", "zoom_0.mp4", "*.mp4")
AUDIO_GLOBS = ("audio*.m4a", "audio_only.m4a", "*.m4a")

DEFAULTS = {
    "WATCH_DIR": "/Users/Shared/ZoomRecordings",
    "CALENDAR_ID": "primary",
    "TIMEZONE": "",       # empty = the Mac's local timezone (recommended)
    "APPEND_DATE": True,
    "RULES": [],          # [{name, keyword, drive_folder_id}]
    "UPLOAD_AUDIO": True,
    "DELETE_AFTER_UPLOAD": True,
    "STABLE_SECONDS": 20,
    "POLL_SECONDS": 30,
    "LOOKUP_WINDOW_MIN": 30,
    "MATCH_TOLERANCE_MIN": 20,
    "GRACE_MIN": 15,
}

log = logging.getLogger("da")


# ---------------------------------------------------------------------------
# Config / state / logging
# ---------------------------------------------------------------------------
def setup_logging():
    LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s")
    log.setLevel(logging.INFO)
    fh = logging.FileHandler(LOG_DIR / "pipeline.log", encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.handlers[:] = [fh, sh]


def load_config():
    if not CONFIG_PATH.exists():
        sys.exit("config.json not found — copy config.example.json to config.json and fill it in.")
    cfg = dict(DEFAULTS)
    cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    cfg["WATCH_DIR"] = os.path.expanduser(str(cfg["WATCH_DIR"]))
    return cfg


def active_rules(cfg):
    """Rules that have a real Drive folder id (placeholders/blanks are inactive)."""
    rules = list(cfg.get("RULES") or [])
    # backward-compat: single KEYWORD + DRIVE_FOLDER_ID
    if not rules and cfg.get("DRIVE_FOLDER_ID"):
        rules = [{"name": "default", "keyword": cfg.get("KEYWORD", ""),
                  "drive_folder_id": cfg["DRIVE_FOLDER_ID"]}]
    out = []
    for r in rules:
        fid = (r.get("drive_folder_id") or "").strip()
        if fid and not fid.startswith("PASTE"):
            out.append(r)
    return out


def load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"done": {}, "skip": {}}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Google auth — one credential for Calendar + Drive
# ---------------------------------------------------------------------------
def google_services():
    if not TOKEN_PATH.exists():
        sys.exit("token.json not found — run:  .venv/bin/python authorize.py")
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json())
        else:
            sys.exit("Google token invalid — re-run:  .venv/bin/python authorize.py")
    cal = build("calendar", "v3", credentials=creds, cache_discovery=False)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    return cal, drive


def _parse_rfc3339(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def find_event(cal, rec_start_utc, cfg):
    """Return the title of the calendar event best matching rec_start_utc, or None."""
    window = timedelta(minutes=cfg["LOOKUP_WINDOW_MIN"])
    resp = cal.events().list(
        calendarId=cfg["CALENDAR_ID"],
        timeMin=(rec_start_utc - window).isoformat(),
        timeMax=(rec_start_utc + window).isoformat(),
        singleEvents=True,
        orderBy="startTime",
        maxResults=15,
    ).execute()

    tol = timedelta(minutes=cfg["MATCH_TOLERANCE_MIN"])
    grace = timedelta(minutes=cfg["GRACE_MIN"])
    best = None  # (not_brackets, abs_diff_seconds, title)
    for ev in resp.get("items", []):
        start = ev.get("start", {})
        end = ev.get("end", {})
        if "dateTime" not in start:
            continue  # skip all-day events
        ev_start = _parse_rfc3339(start["dateTime"])
        ev_end = _parse_rfc3339(end["dateTime"]) if "dateTime" in end else ev_start
        title = (ev.get("summary") or "").strip()
        if not title:
            continue
        brackets = (ev_start - tol) <= rec_start_utc < (ev_end + grace)
        diff = abs((ev_start - rec_start_utc).total_seconds())
        cand = (not brackets, diff, title)
        if best is None or cand < best:
            best = cand

    if best is None:
        return None
    not_brackets, diff, title = best
    if not_brackets and diff > tol.total_seconds():
        return None
    return title


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
def match_rule(rules, title, topic):
    """First rule whose keyword appears in (title + topic). Empty keyword = catch-all."""
    hay = ((title or "") + " " + (topic or "")).lower()
    for r in rules:
        kw = (r.get("keyword") or "").strip().lower()
        if kw == "" or kw in hay:
            return r
    return None


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------
def parse_folder_start(folder):
    m = FOLDER_RE.match(folder.name)
    if not m:
        return None
    y, mo, d, hh, mm, ss = (int(x) for x in m.groups())
    naive = datetime(y, mo, d, hh, mm, ss)
    aware = naive.replace(tzinfo=TZ) if TZ else naive  # naive -> assume Mac local tz
    return aware.astimezone(timezone.utc)


def folder_topic(folder):
    """The Zoom meeting name = folder name with the 'YYYY-MM-DD HH.MM.SS ' prefix removed."""
    m = FOLDER_RE.match(folder.name)
    return folder.name[m.end():].strip() if m else folder.name


def _first_glob(folder, globs):
    for g in globs:
        hits = sorted(folder.glob(g), key=lambda p: p.stat().st_size, reverse=True)
        if hits:
            return hits[0]
    return None


def folder_ready(folder, stable_seconds):
    """Ready = Zoom finished converting AND the video hasn't changed for a while."""
    if list(folder.glob(CONVERTING_GLOB)):
        return None, None
    video = _first_glob(folder, VIDEO_GLOBS)
    if not video:
        return None, None
    if (time.time() - video.stat().st_mtime) < stable_seconds:
        return None, None
    audio = _first_glob(folder, AUDIO_GLOBS)
    return video, audio


def sanitize(name):
    name = name.replace("/", "-").replace(":", "-").replace("\\", "-")
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    return name[:180]


def unique_path(path):
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    i = 2
    while True:
        cand = parent / f"{stem} ({i}){suffix}"
        if not cand.exists():
            return cand
        i += 1


def _md5(path, chunk=1 << 20):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Drive upload + verify
# ---------------------------------------------------------------------------
def trigger_call_analysis(file_id, folder_id, client_name, is_followup=False):
    """Trigger async call analysis (transcription + Claude insights)."""
    try:
        cmd = [
            sys.executable, str(BASE / "call_analyzer.py"),
            "--file-id", file_id,
            "--folder-id", folder_id,
            "--client-name", client_name,
        ]
        if is_followup:
            cmd.append("--followup")

        # Run in background (non-blocking)
        subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        log.info("Analysis queued for %s (file_id=%s)", client_name, file_id)
    except Exception as e:
        log.error("Failed to queue analysis: %s", e)


def trigger_outcome_form(client_name, base_filename, call_time):
    """Trigger a macOS notification + open outcome form in browser."""
    try:
        # macOS notification
        script = f'''
        display notification "✅ Sales call recorded: {client_name}" \\
            with title "Dollar Academy Sales Pipeline" \\
            subtitle "Please fill the outcome form"
        '''
        os.system(f"osascript -e '{script}'")

        # Open form in browser (Typeform/Google Form URL)
        # Replace with your actual form URL
        form_url = "https://forms.gle/YOUR_FORM_ID"  # TODO: replace with actual form
        os.system(f"open '{form_url}?prefill_client={client_name}&prefill_time={call_time.isoformat()}'")
        log.info("Outcome form triggered for %s", client_name)
    except Exception as e:
        log.error("Failed to trigger outcome form: %s", e)


def cleanup_pending_deletions(state, cfg):
    """Check for folders scheduled for deletion and delete if 24h has passed."""
    if not cfg.get("DELETE_AFTER_UPLOAD"):
        return

    pending = state.get("pending_delete", {})
    now = datetime.now(timezone.utc)
    to_delete = []

    for key, info in pending.items():
        delete_at = datetime.fromisoformat(info["delete_at"])
        if now >= delete_at:
            folder_path = Path(info["folder"])
            if folder_path.exists():
                try:
                    shutil.rmtree(folder_path)
                    log.info("DELETED (after 24h): %s", folder_path.name)
                    to_delete.append(key)
                except Exception as e:
                    log.error("Failed to delete %s: %s", folder_path, e)
            else:
                to_delete.append(key)  # already gone

    for key in to_delete:
        del pending[key]

    if to_delete:
        state["pending_delete"] = pending
        save_state(state)


def export_insights_csv(state, output_file):
    """Export all completed calls to CSV for analysis."""
    import csv

    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'date', 'client_name', 'call_type', 'rule', 'duration_minutes',
            'uploaded_at', 'outcome', 'next_action'
        ])
        writer.writeheader()

        for key, info in state.get("done", {}).items():
            writer.writerow({
                'date': info.get('at', ''),
                'client_name': info.get('client_name', ''),
                'call_type': 'Follow-up' if info.get('is_followup') else 'Initial',
                'rule': info.get('rule', ''),
                'duration_minutes': '',  # TODO: extract from recording metadata
                'uploaded_at': info.get('uploaded_at', ''),
                'outcome': info.get('outcome', ''),
                'next_action': info.get('next_action', '')
            })

    log.info("Exported insights to %s", output_file)


def drive_upload(localfile, folder_id, drive):
    meta = {"name": localfile.name, "parents": [folder_id]}
    media = MediaFileUpload(str(localfile), resumable=True, chunksize=64 * 1024 * 1024)
    log.info("uploading: %s (%.1f MB)", localfile.name, localfile.stat().st_size / 1e6)
    req = drive.files().create(
        body=meta, media_body=media,
        fields="id,size,md5Checksum", supportsAllDrives=True,
    )
    resp = None
    while resp is None:
        _, resp = req.next_chunk()

    local_size = localfile.stat().st_size
    remote_size = int(resp.get("size", -1))
    file_id = resp.get("id")
    ok = remote_size == local_size
    if resp.get("md5Checksum"):
        ok = ok and resp["md5Checksum"] == _md5(localfile)
    if not ok:
        log.error("verify failed for %s (local=%d remote=%d)", localfile.name, local_size, remote_size)
        return None

    return file_id  # Return file ID for analysis


# ---------------------------------------------------------------------------
# Core: process one meeting folder
# ---------------------------------------------------------------------------
def extract_client_name(title_or_topic):
    """Extract client name from event title.
    Format: 'פגישת ייעוץ והתאמה למסלול ההכשרה - <CLIENT_NAME> + אקדמיית הדולר'
    Returns the client name between the dashes.
    """
    if not title_or_topic:
        return None
    # Look for pattern: ... - CLIENT_NAME + אקדמיית הדולר
    match = re.search(r'-\s*([^+]+?)\s*\+', title_or_topic)
    if match:
        return match.group(1).strip()
    return None


def is_sales_call(title):
    """Check if this is a sales call (contains 'ייעוץ והתאמה')."""
    if not title:
        return False
    return 'ייעוץ והתאמה' in title


def format_filename_date(when_local):
    """Format date as DD/MM/YYYY."""
    return when_local.strftime("%d/%m/%Y")


def should_ask_for_outcome(title):
    """Return True if we should show the form to ask about call outcome."""
    return is_sales_call(title)


def process_folder(folder, cfg, state, cal, drive, dry=False):
    key = folder.name
    if key in state["done"] or key in state["skip"]:
        return

    rec_start = parse_folder_start(folder)
    if rec_start is None:
        return  # not a Zoom meeting folder

    video, audio = folder_ready(folder, cfg["STABLE_SECONDS"])
    if not video:
        return  # still converting / not finished writing — retry next poll

    rules = active_rules(cfg)
    title = find_event(cal, rec_start, cfg)
    topic = folder_topic(folder)
    rule = match_rule(rules, title, topic)
    when_local = rec_start.astimezone(TZ) if TZ else rec_start.astimezone()

    if rule is None:
        log.info("SKIP (no rule matched)  title=%r  topic=%r", title, topic)
        state["skip"][key] = {"reason": "no_rule", "title": title, "topic": topic,
                              "at": when_local.isoformat()}
        save_state(state)
        return

    # Format filename: DD/MM/YYYY CLIENT_NAME - פגישה מקצועית [/ המשך]
    date_str = format_filename_date(when_local)
    client_name = extract_client_name(title) or "Unknown"
    is_followup = title and title.startswith("המשך") if title else False
    call_type = "המשך פגישה מקצועית" if is_followup else "פגישה מקצועית"
    base = f"{date_str} {client_name} - {call_type}"
    base = sanitize(base)

    log.info("MATCH [%s]  %s  ->  '%s'", rule.get("name", "?"), folder.name, base)

    if dry:
        log.info("[dry-run] would upload to folder %s : video=%s audio=%s",
                 rule["drive_folder_id"], video.name, audio.name if audio else None)
        return

    # Rename video (+ audio)
    targets = []
    new_video = unique_path(folder / f"{base}{video.suffix}")
    video.rename(new_video)
    targets.append(new_video)

    if cfg["UPLOAD_AUDIO"] and audio and audio.exists():
        new_audio = unique_path(folder / f"{base} audio{audio.suffix}")
        audio.rename(new_audio)
        targets.append(new_audio)

    # Upload (verified) — bail before deleting if anything failed
    uploaded_file_ids = []
    for t in targets:
        file_id = drive_upload(t, rule["drive_folder_id"], drive)
        if not file_id:
            log.error("upload/verify failed for %s — leaving local files in place", base)
            return
        uploaded_file_ids.append(file_id)

    state["done"][key] = {
        "title": base,
        "rule": rule.get("name"),
        "at": when_local.isoformat(),
        "client_name": client_name,
        "is_followup": is_followup,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "delete_after": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        "video_file_id": uploaded_file_ids[0] if uploaded_file_ids else None
    }
    save_state(state)
    log.info("UPLOADED [%s]  %s  (%d file/s)", rule.get("name"), base, len(targets))

    # Mark for deletion after 24 hours (if enabled)
    if cfg.get("DELETE_AFTER_UPLOAD"):
        state["pending_delete"] = state.get("pending_delete", {})
        state["pending_delete"][key] = {
            "folder": str(folder),
            "delete_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        }
        save_state(state)
        log.info("SCHEDULED for deletion in 24 hours: %s", folder.name)

    # If this is a sales call, trigger analysis + outcome form
    if should_ask_for_outcome(title):
        log.info("SALES CALL detected — triggering analysis for %s", client_name)
        if uploaded_file_ids:
            trigger_call_analysis(uploaded_file_ids[0], rule["drive_folder_id"], client_name, is_followup)
        trigger_outcome_form(client_name, base, when_local)


def scan(cfg, state, cal, drive, dry=False):
    root = Path(cfg["WATCH_DIR"])
    if not root.is_dir():
        log.error("WATCH_DIR does not exist: %s", root)
        return

    # First, clean up any pending deletions
    cleanup_pending_deletions(state, cfg)

    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        try:
            process_folder(folder, cfg, state, cal, drive, dry)
        except Exception as e:
            log.exception("error processing %s: %s", folder.name, e)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="DA Sales Calls — Zoom→Drive pipeline")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--watch", action="store_true", help="long-running poll loop")
    g.add_argument("--scan", action="store_true", help="process ready recordings once")
    g.add_argument("--once", metavar="PATH", help="process a single meeting folder")
    g.add_argument("--reset-state", action="store_true", help="forget processed/skipped folders")
    ap.add_argument("--dry-run", action="store_true", help="don't rename/upload/delete")
    args = ap.parse_args()

    setup_logging()

    if args.reset_state:
        if STATE_PATH.exists():
            STATE_PATH.unlink()
        log.info("state cleared.")
        return

    cfg = load_config()
    global TZ
    if cfg.get("TIMEZONE"):
        TZ = ZoneInfo(cfg["TIMEZONE"])
    if not args.dry_run and not active_rules(cfg):
        sys.exit("No active RULES with a drive_folder_id set in config.json.")
    state = load_state()
    cal, drive = google_services()

    if args.once:
        process_folder(Path(os.path.expanduser(args.once)), cfg, state, cal, drive, args.dry_run)
        return

    if args.scan:
        scan(cfg, state, cal, drive, args.dry_run)
        return

    # --watch
    rules_desc = [(r.get("name"), r.get("keyword")) for r in active_rules(cfg)]
    log.info("watching %s every %ss — rules=%s delete_after_upload=%s",
             cfg["WATCH_DIR"], cfg["POLL_SECONDS"], rules_desc, cfg["DELETE_AFTER_UPLOAD"])
    while True:
        try:
            scan(cfg, state, cal, drive, args.dry_run)
        except Exception as e:  # pragma: no cover
            log.exception("scan error: %s", e)
        time.sleep(cfg["POLL_SECONDS"])


if __name__ == "__main__":
    main()
