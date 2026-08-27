"""
Africa's Talking SMS gateway (SokoSure-style workflow).

After a USSD action completes, the app fires SMS via AT. SMS is auxiliary:
failures are logged and must not break the USSD session.

Sandbox demo:
  AT_USERNAME=sandbox
  AT_API_KEY=<sandbox key>
  AT_SHORTCODE=<sandbox 2-way shortcode>
  SMS_DRY_RUN=false
"""

import os
import re

from dotenv import load_dotenv

from data import sms_store

load_dotenv()

_sms_client = None


def normalize_phone(phone):
    """Normalize MSISDNs so USSD/SMS callbacks match seeded mechanic numbers."""
    if not phone:
        return ""
    raw = str(phone).strip()
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("0") and len(digits) >= 10:
        digits = "254" + digits[1:]
    elif len(digits) == 9 and digits.startswith("7"):
        digits = "254" + digits
    if digits.startswith("254"):
        return f"+{digits}"
    return raw if raw.startswith("+") else f"+{digits}" if digits else raw


def _explicit_dry_run():
    flag = os.getenv("SMS_DRY_RUN")
    if flag is None:
        return None
    return flag.lower() != "false"


def _credentials_configured():
    key = (os.getenv("AT_API_KEY") or "").strip()
    user = (os.getenv("AT_USERNAME") or "").strip()
    if not key or not user:
        return False
    if key.lower().startswith("your_"):
        return False
    return True


def is_dry_run():
    """
    Dry-run when explicitly enabled, or when AT credentials are missing.
    Mirrors SokoSure (real send when configured) while staying safe locally.
    """
    explicit = _explicit_dry_run()
    if explicit is True:
        return True
    if explicit is False:
        return False
    return not _credentials_configured()


def _sender_id():
    sender = (os.getenv("AT_SHORTCODE") or "").strip()
    if not sender or sender.lower().startswith("your_"):
        return None
    return sender


def _get_sms_client():
    """Lazy-init AT SDK, same idea as SokoSure's NotificationService."""
    global _sms_client
    if is_dry_run():
        return None
    if _sms_client is None:
        import africastalking

        africastalking.initialize(
            username=os.getenv("AT_USERNAME"),
            api_key=os.getenv("AT_API_KEY"),
        )
        _sms_client = africastalking.SMS
    return _sms_client


def send_sms(to, message, *, raise_on_error=False):
    """
    Send an SMS. `to` can be a single phone number string or a list.

    By default does not raise (USSD must still END cleanly, like SokoSure's
    welcome SMS). Pass raise_on_error=True only when the caller needs to know.
    """
    raw_recipients = to if isinstance(to, list) else [to]
    recipients = [normalize_phone(p) for p in raw_recipients]
    recipient = ", ".join(recipients)

    if is_dry_run():
        print("---- [SMS DRY RUN] ----")
        print("To:", recipients)
        print("Message:", message)
        print("------------------------")
        response = {"status": "DRY_RUN_OK", "to": recipients, "message": message}
        sms_store.record_outgoing(recipient, message, "dry_run", response)
        return response

    try:
        client = _get_sms_client()
        sender = _sender_id()
        # SokoSure always passes sender_id when a shortcode is configured.
        if sender:
            response = client.send(message, recipients, sender_id=sender)
        else:
            response = client.send(message, recipients)
        response_recipients = response.get("SMSMessageData", {}).get("Recipients", [])
        recipient_status = (
            response_recipients[0].get("status", "unknown").lower()
            if response_recipients
            else "failed"
        )
        sms_store.record_outgoing(recipient, message, recipient_status, response)
        return response
    except Exception as exc:  # noqa: BLE001
        sms_store.record_outgoing(recipient, message, "failed", error=str(exc))
        print("SMS send failed:", exc)
        if raise_on_error:
            raise
        return {"status": "failed", "error": str(exc), "to": recipients}
