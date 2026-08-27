"""
Inbound SMS webhook for Africa's Talking.

SokoSure-style: AT POSTs replies to the shortcode callback; we advance the
pending dispatch (YES/NO) and SMS the driver. Failures return 200 so AT
does not retry endlessly.
"""

from flask import Blueprint, request, jsonify

from data import sms_store, store
from utils.respond import respond_to_request
from utils.sms import normalize_phone, send_sms

sms_bp = Blueprint("sms", __name__)

ACCEPT_WORDS = {"1", "yes", "y", "accept"}
DECLINE_WORDS = {"2", "no", "n", "decline"}


@sms_bp.route("/sms", methods=["POST"])
@sms_bp.route("/sms/inbound", methods=["POST"])
@sms_bp.route("/sms/incoming", methods=["POST"])
def sms_inbound():
    from_number = normalize_phone(request.values.get("from", ""))
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
        return jsonify({"status": "ignored", "reason": "no pending request"}), 200

    if text in ACCEPT_WORDS:
        ok, status, _ = respond_to_request(req, "accept")
        return jsonify({"status": status, "requestId": req["id"]}), 200

    if text in DECLINE_WORDS:
        ok, status, _ = respond_to_request(req, "decline")
        return jsonify({"status": status, "requestId": req["id"]}), 200

    send_sms(
        from_number,
        "Sorry, we didn't understand that. Reply YES to accept or NO to decline.",
    )
    return jsonify({"status": "unrecognized"}), 200
