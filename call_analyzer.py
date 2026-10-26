#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Call Analyzer — Transcribe, analyze, and extract insights from sales calls.

This agent:
  1. Downloads the recording from Google Drive
  2. Transcribes using OpenAI Whisper
  3. Analyzes the call with Claude AI
  4. Uploads summary back to Drive
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import anthropic
import openai
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

BASE = Path(__file__).resolve().parent
TOKEN_PATH = BASE / "token.json"
SCOPES = ["https://www.googleapis.com/auth/drive"]

log = logging.getLogger("analyzer")


def setup_logging():
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s")
    log.setLevel(logging.INFO)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.handlers[:] = [sh]


def get_drive_service():
    """Get authenticated Google Drive service."""
    if not TOKEN_PATH.exists():
        sys.exit("token.json not found — run:  .venv/bin/python authorize.py")
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json())
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def download_file(drive, file_id, output_path):
    """Download a file from Google Drive."""
    request = drive.files().get_media(fileId=file_id)
    with open(output_path, "wb") as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    log.info("Downloaded: %s", output_path)


def transcribe_audio(audio_path):
    """Transcribe audio using OpenAI Whisper API."""
    log.info("Transcribing: %s", audio_path)
    with open(audio_path, "rb") as f:
        transcript = openai.Audio.transcribe(
            model="whisper-1",
            file=f,
            language="he",  # Hebrew
            response_format="text"
        )
    return transcript


def analyze_call(transcript, client_name, call_type="initial"):
    """Analyze the call transcript with Claude AI."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    prompt = f"""
תמונת המצב:
שם לקוח: {client_name}
סוג שיחה: {"המשך פולואפ" if call_type == "followup" else "פגישה ראשונית"}
זמן: {datetime.now().isoformat()}

תמלול השיחה:
---
{transcript}
---

כעת, בצע ניתוח מפורט של השיחה. תוציא:

1. **סיכום עיקרי** (2-3 משפטים)
   - מה היה הנושא הראשי?
   - מה היתה התוצאה?

2. **ניתוח משתתפים**
   - מי מדבר? (שמות אם יש)
   - מי דמין בשיחה? (אחוזים בערך)

3. **רגעים מפתח**
   - נקודות הסכמה
   - התנגדויות או חששות
   - החלטות שנתקבלו

4. **טכניקות מכירה שעבדו**
   - מה הצליח?
   - מה היה חלש?

5. **המלצות לשיפור**
   - מה להשתפר בפעם הבאה?

6. **המשך צפוי**
   - מה השלב הבא?
   - תאריך follow-up מוצע

תשובה בעברית, קצרה וקריאה.
"""

    message = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=2000,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    return message.content[0].text


def upload_summary(drive, folder_id, filename, summary_content):
    """Upload summary as a text file to Google Drive."""
    summary_filename = f"{filename} - Summary.txt"

    file_metadata = {
        "name": summary_filename,
        "parents": [folder_id],
        "mimeType": "text/plain"
    }

    from io import BytesIO
    media = MediaIoBaseDownload(
        BytesIO(summary_content.encode("utf-8")),
        None,
        chunksize=256 * 1024 * 1024
    )

    # Use a simpler upload method
    from googleapiclient.http import MediaFileUpload as MFU
    import tempfile

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write(summary_content)
        temp_path = f.name

    try:
        media = MFU(temp_path, mimetype="text/plain")
        request = drive.files().create(body=file_metadata, media_body=media, fields="id")
        file_id = request.execute()["id"]
        log.info("Uploaded summary: %s (ID: %s)", summary_filename, file_id)
        return file_id
    finally:
        os.unlink(temp_path)


def analyze_recording(file_id, folder_id, client_name, call_type="initial"):
    """Main workflow: download → transcribe → analyze → upload summary."""
    drive = get_drive_service()

    temp_dir = Path("/tmp/dollar_academy_analysis")
    temp_dir.mkdir(exist_ok=True)

    audio_path = temp_dir / f"{client_name}_{datetime.now().timestamp()}.m4a"

    try:
        # Download
        log.info("Downloading recording for %s...", client_name)
        download_file(drive, file_id, audio_path)

        # Transcribe
        log.info("Transcribing audio...")
        transcript = transcribe_audio(str(audio_path))

        # Analyze
        log.info("Analyzing call with Claude...")
        analysis = analyze_call(transcript, client_name, call_type)

        # Create summary with transcript
        summary = f"""
📞 ניתוח שיחת מכירה
{'='*50}

לקוח: {client_name}
סוג שיחה: {"המשך פולואפ" if call_type == "followup" else "פגישה ראשונית"}
תאריך: {datetime.now().isoformat()}

📋 ניתוח
{'-'*50}
{analysis}

📝 תמלול מלא
{'-'*50}
{transcript}
"""

        # Upload summary
        log.info("Uploading summary to Drive...")
        upload_summary(drive, folder_id, client_name, summary)

        log.info("✅ Analysis complete for %s", client_name)
        return analysis

    finally:
        # Cleanup
        if audio_path.exists():
            audio_path.unlink()


def main():
    ap = argparse.ArgumentParser(description="Analyze sales call recordings")
    ap.add_argument("--file-id", required=True, help="Google Drive file ID of recording")
    ap.add_argument("--folder-id", required=True, help="Google Drive folder ID (for summary)")
    ap.add_argument("--client-name", required=True, help="Client name")
    ap.add_argument("--followup", action="store_true", help="Is this a follow-up call?")

    args = ap.parse_args()

    setup_logging()

    call_type = "followup" if args.followup else "initial"
    analysis = analyze_recording(args.file_id, args.folder_id, args.client_name, call_type)
    print("\n" + analysis)


if __name__ == "__main__":
    main()
