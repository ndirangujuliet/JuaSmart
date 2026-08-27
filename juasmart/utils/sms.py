"""
Thin wrapper around Africa's Talking's SMS API.

Defaults to "dry run" mode (SMS_DRY_RUN=true), which just prints the message
to the console instead of sending it. This lets you build and test the
whole USSD + SMS flow locally without needing live Africa's Talking
credentials. Flip SMS_DRY_RUN=false in your environment once you have them.
"""

import os
from dotenv import load_dotenv

from data import sms_store

load_dotenv()

DRY_RUN = os.getenv("SMS_DRY_RUN", "true").lower() != "false"

_sms_client = None

if not DRY_RUN:
    import africastalking

    africastalking.initialize(
        username=os.getenv("AT_USERNAME"),
        api_key=os.getenv("AT_API_KEY"),
    )
    _sms_client = africastalking.SMS


def send_sms(to, message):
    """
    Send an SMS. `to` can be a single phone number string or a list.
    Returns the Africa's Talking response dict, or a dry-run stub.
    """
    recipients = to if isinstance(to, list) else [to]
    recipient = ", ".join(recipients)

    if DRY_RUN:
        print("---- [SMS DRY RUN] ----")
        print("To:", recipients)
        print("Message:", message)
        print("------------------------")
        response = {"status": "DRY_RUN_OK", "to": recipients, "message": message}
        sms_store.record_outgoing(recipient, message, "dry_run", response)
        return response

    try:
        sender = os.getenv("AT_SHORTCODE") or None
        if os.getenv("AT_USERNAME") == "sandbox":
            response = _sms_client.send(message, recipients)
        else:
            response = _sms_client.send(message, recipients, sender_id=sender)
        response_recipients = response.get("SMSMessageData", {}).get("Recipients")
        status = "sent" if response_recipients else "failed"
        sms_store.record_outgoing(recipient, message, status, response)
        return response
    except Exception as exc:  # noqa: BLE001
        sms_store.record_outgoing(recipient, message, "failed", error=str(exc))
        print("SMS send failed:", exc)
        raise
