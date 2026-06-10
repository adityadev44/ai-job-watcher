import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import re
import smtplib
import textwrap
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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

def format_job_message(job):
    """Format a single matched job into a notification string."""
    title = job.get("title", "N/A")
    company = job.get("company", "N/A")
    location = job.get("location", "N/A")
    url = job.get("url", "N/A")
    return (
        f"<b>{title}</b>\n"
        f"Company : {company}\n"
        f"Location: {location}\n"
        f"URL     : {url}"
    )


def notify_matches(jobs):
    """Send Telegram + email alerts for a list of matched jobs. Each channel fails independently."""
    if not jobs:
        return

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


def notify_digest(near_misses_text):
    """Send the weekly near-miss digest. Each channel fails independently."""
    if not near_misses_text:
        return

    send_telegram(near_misses_text)
    send_email(
        subject="Aviation MRO near-misses — weekly digest",
        body=near_misses_text,
    )
