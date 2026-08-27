"""
USSD webhook for Africa's Talking.

Africa's Talking calls this endpoint on every keypress in a USSD session.
It POSTs the FULL text the user has typed so far this session, with each
menu level separated by "*" (e.g. "1*2*3"). There's no server-side session
state to manage — the whole menu path is reconstructed from `text` on every
request.

Response format: a plain-text string starting with:
  "CON ..."  -> keep the session open, show more menu
  "END ..."  -> close the session, this is the final message
"""

from flask import Blueprint, request, Response

from data import store
from utils.sms import send_sms

ussd_bp = Blueprint("ussd", __name__)


def _menu_response(body, end=False):
    prefix = "END" if end else "CON"
    return Response(f"{prefix} {body}", mimetype="text/plain")


def _locations_menu_text():
    lines = ["Select your location:"]
    for loc in store.get_locations():
        lines.append(f"{loc['id']}. {loc['name']}")
    return "\n".join(lines)


def _services_menu_text():
    lines = ["What service do you need?"]
    for svc in store.get_services():
        lines.append(f"{svc['id']}. {svc['name']}")
    return "\n".join(lines)


def _mechanics_list_text(mechanics, location_name):
    if not mechanics:
        return f"Sorry, no available mechanics found near {location_name} right now."
    lines = [f"Available mechanics near {location_name}:"]
    for i, m in enumerate(mechanics, start=1):
        lines.append(f"{i}. {m['name']} - {m['distance_km']} km")
    lines.append("Reply with the number to request assistance.")
    return "\n".join(lines)


def _dispatch_request(driver_phone, mechanic, location, service):
    """
    Create the request, then fire SMS (SokoSure-style USSD → SMS handoff).

    SMS failures are swallowed so the USSD session can still END cleanly.
    """
    from utils.sms import normalize_phone

    driver_phone = normalize_phone(driver_phone)
    req = store.create_request(
        driver_phone=driver_phone,
        mechanic_id=mechanic["id"],
        location_id=location["id"],
        service_id=service["id"],
    )
    mechanic_sms = (
        "NEW BREAKDOWN REQUEST\n"
        f"Ref: {req['id']}\n"
        f"Service: {service['name']}\n"
        f"Location: {location['name']}\n"
        f"Customer: {driver_phone}\n"
        "Reply YES to ACCEPT or NO to DECLINE"
    )
    driver_sms = (
        "JuaSmart: request sent.\n"
        f"Ref: {req['id']}\n"
        f"Garage: {mechanic['name']}\n"
        "You'll get another SMS when they reply YES or NO."
    )
    # Same pattern as SokoSure welcome SMS after registration: try/except,
    # never break the USSD END response.
    try:
        send_sms(mechanic["phone"], mechanic_sms)
    except Exception:  # noqa: BLE001
        pass
    try:
        send_sms(driver_phone, driver_sms)
    except Exception:  # noqa: BLE001
        pass
    return req


@ussd_bp.route("/ussd", methods=["POST"])
def ussd():
    phone_number = request.values.get("phoneNumber", "")
    text = request.values.get("text", "").strip()

    parts = text.split("*") if text else []

    # ---- Root menu ---------------------------------------------------
    if text == "":
        return _menu_response(
            "Welcome to JuaSmart\n"
            "1. Find a mechanic\n"
            "2. Report breakdown\n"
            "3. Find specific service\n"
            "4. My requests\n"
            "5. Register as mechanic"
        )

    root = parts[0]

    # ---- 1. Find a mechanic: location -> service -> mechanic list ----
    if root == "1":
        if len(parts) == 1:
            return _menu_response(_locations_menu_text())

        if len(parts) == 2:
            return _menu_response(_services_menu_text())

        if len(parts) == 3:
            location = store.get_location_by_id(parts[1])
            service = store.get_service_by_id(parts[2])
            if not location or not service:
                return _menu_response("Invalid selection.", end=True)
            mechanics = store.find_mechanics(location["id"], service["id"])
            return _menu_response(_mechanics_list_text(mechanics, location["name"]))

        if len(parts) == 4:
            location = store.get_location_by_id(parts[1])
            service = store.get_service_by_id(parts[2])
            if not location or not service:
                return _menu_response("Invalid selection.", end=True)
            mechanics = store.find_mechanics(location["id"], service["id"])
            try:
                chosen = mechanics[int(parts[3]) - 1]
            except (ValueError, IndexError):
                return _menu_response("Invalid mechanic selection.", end=True)

            req = _dispatch_request(phone_number, chosen, location, service)
            return _menu_response(
                f"Request sent to {chosen['name']}.\n"
                f"Ref: {req['id']}\n"
                "Check your SMS for confirmation.\n"
                "You'll get another SMS once they respond.",
                end=True,
            )

    # ---- 2. Report breakdown: location -> auto "General repair" ----
    if root == "2":
        general_service = store.get_service_by_id(6)  # General repair

        if len(parts) == 1:
            return _menu_response(_locations_menu_text())

        if len(parts) == 2:
            location = store.get_location_by_id(parts[1])
            if not location:
                return _menu_response("Invalid selection.", end=True)
            mechanics = store.find_mechanics(location["id"], general_service["id"])
            return _menu_response(_mechanics_list_text(mechanics, location["name"]))

        if len(parts) == 3:
            location = store.get_location_by_id(parts[1])
            if not location:
                return _menu_response("Invalid selection.", end=True)
            mechanics = store.find_mechanics(location["id"], general_service["id"])
            try:
                chosen = mechanics[int(parts[2]) - 1]
            except (ValueError, IndexError):
                return _menu_response("Invalid mechanic selection.", end=True)

            req = _dispatch_request(phone_number, chosen, location, general_service)
            return _menu_response(
                f"Request sent to {chosen['name']}.\n"
                f"Ref: {req['id']}\n"
                "Check your SMS for confirmation.\n"
                "You'll get another SMS once they respond.",
                end=True,
            )

    # ---- 3. Find specific service: service -> location -> mechanics ----
    if root == "3":
        if len(parts) == 1:
            return _menu_response(_services_menu_text())

        if len(parts) == 2:
            return _menu_response(_locations_menu_text())

        if len(parts) == 3:
            service = store.get_service_by_id(parts[1])
            location = store.get_location_by_id(parts[2])
            if not service or not location:
                return _menu_response("Invalid selection.", end=True)
            mechanics = store.find_mechanics(location["id"], service["id"])
            return _menu_response(_mechanics_list_text(mechanics, location["name"]))

        if len(parts) == 4:
            service = store.get_service_by_id(parts[1])
            location = store.get_location_by_id(parts[2])
            if not service or not location:
                return _menu_response("Invalid selection.", end=True)
            mechanics = store.find_mechanics(location["id"], service["id"])
            try:
                chosen = mechanics[int(parts[3]) - 1]
            except (ValueError, IndexError):
                return _menu_response("Invalid mechanic selection.", end=True)

            req = _dispatch_request(phone_number, chosen, location, service)
            return _menu_response(
                f"Request sent to {chosen['name']}.\n"
                f"Ref: {req['id']}\n"
                "Check your SMS for confirmation.\n"
                "You'll get another SMS once they respond.",
                end=True,
            )

    # ---- 4. My requests: show status of latest request ----------------
    if root == "4":
        from utils.sms import normalize_phone

        driver = normalize_phone(phone_number)
        my_requests = [
            r for r in store.REQUESTS if store._normalize_phone(r["driver_phone"]) == driver
        ]
        if not my_requests:
            return _menu_response("You have no requests yet.", end=True)
        latest = sorted(my_requests, key=lambda r: r["created_at"])[-1]
        mechanic = store.get_mechanic_by_id(latest["mechanic_id"])
        return _menu_response(
            f"Ref: {latest['id']}\n"
            f"Mechanic: {mechanic['name'] if mechanic else 'Unknown'}\n"
            f"Status: {latest['status']}",
            end=True,
        )

    # ---- 5. Register as mechanic: name -> location -> services -------
    if root == "5":
        if len(parts) == 1:
            return _menu_response("Enter your garage/business name:")

        if len(parts) == 2:
            return _menu_response(_locations_menu_text())

        if len(parts) == 3:
            return _menu_response(
                _services_menu_text()
                + "\n\nEnter numbers separated by commas (e.g. 1,3,6)"
            )

        if len(parts) == 4:
            name = parts[1]
            location = store.get_location_by_id(parts[2])
            if not location:
                return _menu_response("Invalid location.", end=True)
            try:
                service_ids = [s.strip() for s in parts[3].split(",")]
                service_ids = [
                    s for s in service_ids if store.get_service_by_id(s)
                ]
                if not service_ids:
                    raise ValueError
            except ValueError:
                return _menu_response("Invalid service selection.", end=True)

            mechanic = store.register_mechanic(
                name=name,
                phone=phone_number,
                location_id=location["id"],
                service_ids=service_ids,
            )
            return _menu_response(
                f"Registered! Welcome, {mechanic['name']}.\n"
                f"Location: {location['name']}\n"
                "You'll receive breakdown requests by SMS.",
                end=True,
            )

    # ---- Fallback -----------------------------------------------------
    return _menu_response("Invalid option. Please try again.", end=True)
