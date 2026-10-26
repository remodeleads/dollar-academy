#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Outcome Form Server — Handle form submissions and route deals.

Receives POST requests from outcome_form.html and:
  1. Saves submission to state.json
  2. Routes to appropriate Drive folder based on outcome
  3. Triggers follow-up reminders if needed
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import threading

BASE = Path(__file__).resolve().parent
STATE_PATH = BASE / "state.json"
PORT = 8765

log = logging.getLogger("form_server")


def setup_logging():
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s")
    log.setLevel(logging.INFO)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.handlers[:] = [sh]


def load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"done": {}, "skip": {}, "outcomes": {}}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def process_outcome(submission, state):
    """Process the outcome submission and update routing."""
    client_name = submission.get("clientName", "Unknown")
    outcome = submission.get("outcome", "")
    followup_date = submission.get("followupDate", "")

    log.info("Processing outcome for %s: %s", client_name, outcome)

    # Find matching call in state
    matching_key = None
    for key, info in state.get("done", {}).items():
        if info.get("client_name") == client_name:
            matching_key = key
            break

    if matching_key:
        state["done"][matching_key].update({
            "outcome": outcome,
            "followup_date": followup_date,
            "next_steps": submission.get("nextSteps", ""),
            "deal_value": submission.get("dealValue", ""),
            "key_points": submission.get("keyPoints", ""),
            "notes": submission.get("notes", ""),
            "outcome_submitted_at": submission.get("submittedAt", "")
        })

        # Determine routing
        if outcome == "closed_positive":
            routing = "CLOSED_DEALS"
            state["done"][matching_key]["routing"] = routing
            log.info("✅ CLOSED DEAL: %s → נסלקו כבר folder", client_name)

        elif outcome == "closed_negative":
            routing = "CLOSED_NEGATIVE"
            state["done"][matching_key]["routing"] = routing
            log.info("❌ CLOSED NEGATIVE: %s → archive", client_name)

        elif outcome in ["open_interested", "open_thinking"]:
            routing = "OPEN_LEADS"
            state["done"][matching_key]["routing"] = routing
            log.info("🔄 OPEN: %s → open leads folder", client_name)

        elif outcome == "follow_needed":
            if followup_date:
                reminder_time = datetime.fromisoformat(followup_date).isoformat()
                state["done"][matching_key]["routing"] = "OPEN_LEADS"
                state["done"][matching_key]["reminder_at"] = reminder_time
                log.info("⏳ FOLLOW-UP SET: %s → %s", client_name, followup_date)

        save_state(state)
        return True

    else:
        log.warning("No matching call found for %s", client_name)
        return False


class FormRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for form submissions."""

    def do_POST(self):
        """Handle POST request from form."""
        if self.path != "/api/submit_outcome":
            self.send_response(404)
            self.end_headers()
            return

        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            submission = json.loads(body)

            log.info("Form submission received from %s", submission.get("clientName"))

            # Load state and process
            state = load_state()
            success = process_outcome(submission, state)

            if success:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                response = {
                    "status": "success",
                    "message": "Outcome recorded successfully"
                }
                self.wfile.write(json.dumps(response).encode("utf-8"))
            else:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                response = {
                    "status": "error",
                    "message": "Could not find matching call"
                }
                self.wfile.write(json.dumps(response).encode("utf-8"))

        except Exception as e:
            log.error("Error processing form submission: %s", e)
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = {"status": "error", "message": str(e)}
            self.wfile.write(json.dumps(response).encode("utf-8"))

    def do_GET(self):
        """Serve outcome_form.html"""
        if self.path.startswith("/form"):
            form_path = BASE / "outcome_form.html"
            if form_path.exists():
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(form_path.read_bytes())
            else:
                self.send_response(404)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress default HTTP logging."""
        pass


def start_server():
    """Start the form server."""
    setup_logging()
    log.info("Starting form server on http://localhost:%d", PORT)
    server = HTTPServer(("127.0.0.1", PORT), FormRequestHandler)
    log.info("Server ready. Serve form at: http://localhost:%d/form", PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down...")
        server.shutdown()


def main():
    ap = argparse.ArgumentParser(description="Outcome form server")
    ap.add_argument("--port", type=int, default=PORT, help=f"Port to run on (default: {PORT})")
    args = ap.parse_args()

    global PORT
    PORT = args.port

    start_server()


if __name__ == "__main__":
    main()
