"""
Inbound SMS webhook for Africa's Talking.

When a mechanic replies "YES" or "NO" to a breakdown request SMS, Africa's
Talking POSTs the reply here. We find that mechanic's most recent pending
request and update it, then notify the driver by SMS.
"""

from flask import Blueprint, request, jsonify

from data import store
from utils.sms import send_sms

sms_bp = Blueprint("sms", __name__)

ACCEPT_WORDS = {"1", "yes", "y", "accept"}
DECLINE_WORDS = {"2", "no", "n", "decline"}

# Roughly how long a mechanic typically takes to reach the driver.
# In production this could vary by mechanic or by distance instead of
# being a flat number.
DEFAULT_ETA_MINUTES = 15


@sms_bp.route("/sms/inbound", methods=["POST"])
@sms_bp.route("/sms/incoming", methods=["POST"])
def sms_inbound():
    from_number = request.values.get("from", "")
    text = request.values.get("text", "").strip().lower()
    sms_store.record_sms(
        from_number,
        text,
        "received",
        {"messageId": request.values.get("id", "")},
        direction="incoming",
    )

    req = store.get_pending_request_for_mechanic(from_number)
    if not req:
        # Nothing pending for this number — nothing to do, but still
        # return 200 so Africa's Talking doesn't retry.
        return jsonify({"status": "ignored", "reason": "no pending request"}), 200

    mechanic = store.get_mechanic_by_id(req["mechanic_id"])
    location = store.get_location_by_id(req["location_id"])
    service = store.get_service_by_id(req["service_id"])

    if text in ACCEPT_WORDS:
        store.update_request_status(req["id"], "ACCEPTED")
        send_sms(
            req["driver_phone"],
            (
                f"{mechanic['name']} has accepted your request.\n"
                f"Mechanic: {mechanic['name']}\n"
                f"Service: {service['name']}\n"
                f"Contact: {mechanic['phone']}\n"
                f"ETA: {DEFAULT_ETA_MINUTES} minutes."
            ),
        )
        return jsonify({"status": "accepted", "requestId": req["id"]}), 200

    if text in DECLINE_WORDS:
        store.update_request_status(req["id"], "DECLINED")
        send_sms(
            req["driver_phone"],
            (
                f"{mechanic['name']} is unavailable right now.\n"
                "Dial *123# and choose 'Find a mechanic' to try another garage."
            ),
        )
        return jsonify({"status": "declined", "requestId": req["id"]}), 200

    # Unrecognized reply
    send_sms(
        from_number,
        "Sorry, we didn't understand that. Reply YES to accept or NO to decline.",
    )
    return jsonify({"status": "unrecognized"}), 200
