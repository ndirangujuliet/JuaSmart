"""
Shared mechanic accept/decline handling for USSD and inbound SMS.
"""

from data import store
from utils.sms import send_sms

DEFAULT_ETA_MINUTES = 15


def respond_to_request(req, decision):
    """
    Mark a pending request ACCEPTED or DECLINED and SMS the client.

    `decision` is "accept" or "decline".
    Returns (ok: bool, status: str, message: str).
    """
    if not req or req.get("status") != "PENDING":
        return False, "ignored", "No pending request."

    mechanic = store.get_mechanic_by_id(req["mechanic_id"])
    service = store.get_service_by_id(req["service_id"])
    if not mechanic or not service:
        return False, "error", "Request data incomplete."

    if decision == "accept":
        store.update_request_status(req["id"], "ACCEPTED")
        client_label = req.get("client_name") or "Customer"
        send_sms(
            req["driver_phone"],
            (
                f"{mechanic['name']} has accepted your request.\n"
                f"Hi {client_label},\n"
                f"Mechanic: {mechanic['name']}\n"
                f"Service: {service['name']}\n"
                f"Contact: {mechanic['phone']}\n"
                f"ETA: {DEFAULT_ETA_MINUTES} minutes."
            ),
        )
        return True, "accepted", f"Accepted request {req['id']}."

    if decision == "decline":
        store.update_request_status(req["id"], "DECLINED")
        send_sms(
            req["driver_phone"],
            (
                f"{mechanic['name']} is unavailable right now.\n"
                "Dial the JuaSmart code and choose 'Find a mechanic' "
                "to try another garage."
            ),
        )
        return True, "declined", f"Declined request {req['id']}."

    return False, "unrecognized", "Unknown decision."
