import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
import os
import re
import smtplib
import tempfile
import textwrap
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

# ── Location-priority sort (India → Middle East → Singapore/Asia → Others) ──

_INDIA = ["india", "mumbai", "delhi", "bangalore", "bengaluru", "hyderabad",
          "chennai", "pune", "kolkata", "gurgaon", "gurugram", "noida"]
_MIDEAST = ["uae", "dubai", "abu dhabi", "sharjah", "doha", "qatar", "riyadh",
            "saudi", "jeddah", "bahrain", "kuwait", "oman", "muscat",
            "cairo", "egypt", "jordan", "amman", "beirut"]
_ASIA = ["singapore", "malaysia", "kuala lumpur", "thailand", "bangkok",
         "indonesia", "jakarta", "hong kong", "japan", "tokyo", "korea",
         "taiwan", "china", "philippines", "vietnam", "australia", "sydney",
         "melbourne", "new zealand"]


def _location_priority(location: str) -> int:
    loc = location.lower()
    if any(kw in loc for kw in _INDIA):
        return 0
    if any(kw in loc for kw in _MIDEAST):
        return 1
    if any(kw in loc for kw in _ASIA):
        return 2
    return 3


def _date_sortable(job: dict) -> str:
    """Return a YYYY-MM-DD string for sorting. Falls back to '0000-00-00'."""
    for key in ("posting_date", "date", "postedDate", "dateCreated"):
        val = str(job.get(key, "") or "")
        if not val:
            continue
        m = re.search(r"(\d{4}-\d{2}-\d{2})", val)
        if m:
            return m.group(1)
        m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", val)   # D[D]/M[M]/YYYY (Safran)
        if m:
            return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    return "0000-00-00"


def _sort_for_alert(jobs: list) -> list:
    """Sort matches: India first, then Middle East, then Singapore/Asia, then others.
    Within each region, newest posting date first."""
    by_date = sorted(jobs, key=_date_sortable, reverse=True)
    return sorted(by_date, key=lambda j: _location_priority(j.get("location", "")))

try:
    from dotenv import load_dotenv
    load_dotenv(override=False)  # graceful no-op if .env absent (cloud runs)
except ImportError:
    pass

import requests


def _env(key):
    return os.environ.get(key, "").strip()


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

TELEGRAM_MAX_CHARS = 4000  # Telegram message limit is ~4096; leave headroom


def _send_telegram_chunk(bot_token, chat_id, text):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    resp = requests.post(url, json=payload, timeout=15)
    resp.raise_for_status()


def send_telegram(message, bot_token=None, chat_id=None):
    """Send message via Telegram, splitting into chunks if needed."""
    bot_token = bot_token or _env("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or _env("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print("[notifier] Telegram not configured — skipping.")
        return

    try:
        chunks = textwrap.wrap(message, TELEGRAM_MAX_CHARS, break_long_words=False, replace_whitespace=False)
        if not chunks:
            chunks = [message]
        for chunk in chunks:
            _send_telegram_chunk(bot_token, chat_id, chunk)
        print(f"[notifier] Telegram: sent {len(chunks)} chunk(s).")
    except Exception as exc:
        print(f"[notifier] Telegram error (non-fatal): {exc}")


# ---------------------------------------------------------------------------
# Gmail / SMTP
# ---------------------------------------------------------------------------

def send_email(subject, body, recipient=None, gmail_user=None, gmail_password=None):
    """Send email via Gmail SMTP. Fails independently — never crashes the run."""
    recipient = recipient or _env("ALERT_RECIPIENT")
    gmail_user = gmail_user or _env("GMAIL_USER")
    gmail_password = gmail_password or _env("GMAIL_APP_PASSWORD")

    if not all([recipient, gmail_user, gmail_password]):
        print("[notifier] Email not configured — skipping.")
        return

    # Support comma- or semicolon-separated recipient lists
    recipient_list = [r.strip() for r in re.split(r"[;,]", recipient) if r.strip()]

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = gmail_user
        msg["To"] = ", ".join(recipient_list)
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            server.login(gmail_user, gmail_password)
            server.sendmail(gmail_user, recipient_list, msg.as_string())

        print(f"[notifier] Email sent to {len(recipient_list)} recipient(s).")
    except Exception as exc:
        print(f"[notifier] Email error (non-fatal): {exc}")


# ---------------------------------------------------------------------------
# High-level helpers
# ---------------------------------------------------------------------------

def _display_date(job: dict) -> str:
    """Return a YYYY-MM-DD string for display, falling back to the raw value or 'N/A'."""
    d = _date_sortable(job)
    if d != "0000-00-00":
        return d
    for key in ("posting_date", "date", "postedDate", "dateCreated"):
        val = str(job.get(key, "") or "").strip()
        if val:
            return val
    return "N/A"


def format_job_message(job):
    """Format a single matched job into a notification string."""
    title = job.get("title", "N/A")
    company = job.get("company", "N/A")
    location = job.get("location", "N/A")
    url = job.get("url", "N/A")
    posted = _display_date(job)
    return (
        f"<b>{title}</b>\n"
        f"Company : {company}\n"
        f"Location: {location}\n"
        f"Posted  : {posted}\n"
        f"URL     : {url}"
    )


def notify_matches(jobs):
    """Send Telegram + email alerts for a list of matched jobs. Each channel fails independently."""
    if not jobs:
        return

    jobs = _sort_for_alert(jobs)

    lines = [f"Aviation MRO — {len(jobs)} new job match(es):\n"]
    for job in jobs:
        lines.append(format_job_message(job))
        lines.append("")

    message = "\n".join(lines)

    send_telegram(message)
    send_email(
        subject="Aviation MRO job matches",
        body=message.replace("<b>", "").replace("</b>", ""),
    )


_FAILURES_PATH = Path(__file__).parent.parent / "pipeline_failures.json"
_FAILURE_THRESHOLD = 3


def _read_failures() -> dict:
    try:
        return json.loads(_FAILURES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_failures(data: dict) -> None:
    dir_ = _FAILURES_PATH.parent
    with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False, suffix=".tmp", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        tmp = f.name
    os.replace(tmp, _FAILURES_PATH)


def notify_pipeline_error(source: str, exc: Exception) -> None:
    """Email when a pipeline crashes 3 consecutive times. Silent on 1st/2nd failure."""
    try:
        data = _read_failures()
        data[source] = data.get(source, 0) + 1
        count = data[source]
        _write_failures(data)
        print(f"[{source}] Consecutive failure count: {count}/{_FAILURE_THRESHOLD}")
        if count < _FAILURE_THRESHOLD:
            return
        # Threshold reached — alert, then reset so next streak of 3 also triggers
        data[source] = 0
        _write_failures(data)
        send_email(
            subject=f"[{source}] pipeline error — Aviation MRO Watcher ({_FAILURE_THRESHOLD} consecutive failures)",
            body=(
                f"The [{source}] pipeline has failed {_FAILURE_THRESHOLD} consecutive times "
                f"and did not run.\n\nMost recent error: {exc}"
            ),
        )
        print(f"[{source}] Error notification sent after {_FAILURE_THRESHOLD} consecutive failures.")
    except Exception:
        pass


def reset_failure_count(source: str) -> None:
    """Reset consecutive failure counter after a successful run."""
    try:
        data = _read_failures()
        if data.get(source, 0) != 0:
            data[source] = 0
            _write_failures(data)
    except Exception:
        pass


def notify_digest(near_misses_text):
    """Send the weekly near-miss digest. Each channel fails independently."""
    if not near_misses_text:
        return

    send_telegram(near_misses_text)
    send_email(
        subject="Aviation MRO near-misses — weekly digest",
        body=near_misses_text,
    )
