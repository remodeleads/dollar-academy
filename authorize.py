#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
One-time Google authorization.
Reads credentials.json (your OAuth "Desktop app" client) and opens a browser
so you can grant, with ONE sign-in:
  • read-only access to your Google Calendar, and
  • upload access to Google Drive.
Saves token.json, which the pipeline reuses (and auto-refreshes) from then on.

Run once:
    .venv/bin/python authorize.py
"""
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

BASE = Path(__file__).resolve().parent
CREDS_PATH = BASE / "credentials.json"
TOKEN_PATH = BASE / "token.json"
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive",
]


def main():
    if not CREDS_PATH.exists():
        raise SystemExit(
            "credentials.json not found.\n"
            "Download it from Google Cloud Console → Credentials → your\n"
            "'Desktop app' OAuth client → Download JSON, and save it here as\n"
            f"{CREDS_PATH}"
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
    # access_type=offline + prompt=consent → we get a long-lived refresh token
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    TOKEN_PATH.write_text(creds.to_json())
    print(f"✅ Saved {TOKEN_PATH}. You're authorized.")


if __name__ == "__main__":
    main()
