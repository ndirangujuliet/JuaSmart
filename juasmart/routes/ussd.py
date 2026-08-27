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

import re

from flask import Blueprint, request, Response

from data import store
from utils.sms import send_sms

ussd_bp = Blueprint("ussd", __name__)
SESSION_LANGUAGES = {}

TRANSLATIONS = {
    "en": {
        "select_location": "Select your location:",
        "service_needed": "What service do you need?",
        "available": "Available mechanics near {location}:",
        "no_mechanics": "Sorry, no available mechanics found near {location} right now.",
        "choose_mechanic": "Reply with the number to request assistance.",
        "language": "Choose language:\n1. English\n2. Kiswahili",
        "language_saved": "Language set to English.",
        "language_saved_sw": "Lugha imewekwa kuwa Kiswahili.",
        "name": "Enter your garage/business name:",
        "services_hint": "Enter numbers separated by commas (e.g. 1,3,6)",
        "invalid": "Invalid selection.",
        "invalid_mechanic": "Invalid mechanic selection.",
        "other_location": "Enter your county name:",
        "phone": "Enter your phone number:",
        "email": "Enter your email address:",
        "welcome": "Welcome to JuaSmart",
        "find_mechanic": "Find a mechanic",
        "report_breakdown": "Report breakdown",
        "find_service": "Find specific service",
        "my_requests": "My requests",
        "register_mechanic": "Register as mechanic",
    },
    "sw": {
        "select_location": "Chagua eneo lako:",
        "service_needed": "Unahitaji huduma gani?",
        "available": "Mafundi wanaopatikana karibu na {location}:",
        "no_mechanics": "Samahani, hakuna fundi anayepatikana karibu na {location} kwa sasa.",
        "choose_mechanic": "Jibu kwa nambari kuomba msaada.",
        "language": "Chagua lugha:\n1. Kiingereza\n2. Kiswahili",
        "language_saved": "Lugha imewekwa kuwa Kiingereza.",
        "language_saved_sw": "Lugha imewekwa kuwa Kiswahili.",
        "name": "Ingiza jina la karakana/biashara:",
        "services_hint": "Ingiza nambari zikitenganishwa kwa koma (mfano 1,3,6)",
        "invalid": "Chaguo si sahihi.",
        "invalid_mechanic": "Chaguo la fundi si sahihi.",
        "other_location": "Ingiza jina la kaunti yako:",
        "phone": "Ingiza nambari yako ya simu:",
        "email": "Ingiza anwani yako ya barua pepe:",
        "welcome": "Karibu JuaSmart",
        "find_mechanic": "Tafuta fundi",
        "report_breakdown": "Ripoti kuharibika kwa gari",
        "find_service": "Tafuta huduma maalum",
        "my_requests": "Maombi yangu",
        "register_mechanic": "Jisajili kama fundi",
    },
}


def _menu_response(body, end=False):
    prefix = "END" if end else "CON"
    return Response(f"{prefix} {body}", mimetype="text/plain")


def _main_menu_text(language):
    labels = TRANSLATIONS[language]
    return (
        f"{labels['welcome']}\n"
        f"1. {labels['find_mechanic']}\n"
        f"2. {labels['report_breakdown']}\n"
        f"3. {labels['find_service']}\n"
        f"4. {labels['my_requests']}\n"
        f"5. {labels['register_mechanic']}"
    )


def _locations_menu_text(language="en"):
    lines = [TRANSLATIONS[language]["select_location"]]
    for loc in store.get_locations():
        if loc["id"] != 48:
            lines.append(f"{loc['id']}. {loc['name']}")
    lines.append("48. Other")
    lines.append(TRANSLATIONS[language]["other_location"])
    return "\n".join(lines)


def _services_menu_text(language="en"):
    lines = [TRANSLATIONS[language]["service_needed"]]
    for svc in store.get_services():
        lines.append(f"{svc['id']}. {svc['name']}")
    return "\n".join(lines)


def _mechanics_list_text(mechanics, location_name, language="en"):
    if not mechanics:
        return TRANSLATIONS[language]["no_mechanics"].format(location=location_name)
    lines = [TRANSLATIONS[language]["available"].format(location=location_name)]
    for i, m in enumerate(mechanics, start=1):
        lines.append(f"{i}. {m['name']} - {m['distance_km']} km")
    lines.append(TRANSLATIONS[language]["choose_mechanic"])
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
    session_id = request.values.get("sessionId", "")
    phone_number = request.values.get("phoneNumber", "")
    text = request.values.get("text", "").strip()
    language = SESSION_LANGUAGES.get(session_id, "en")

    parts = text.split("*") if text else []

    # ---- Language selection and root menu ---------------------------
    if text == "":
        return _menu_response("Choose language / Chagua lugha:\n1. English\n2. Kiswahili")

    if not session_id or session_id not in SESSION_LANGUAGES:
        root = parts[0] if parts else ""
        if root not in {"1", "2"} or len(parts) != 1:
            return _menu_response("Choose language / Chagua lugha:\n1. English\n2. Kiswahili", end=True)
        language = "en" if root == "1" else "sw"
        SESSION_LANGUAGES[session_id] = language
        return _menu_response(_main_menu_text(language))

    # The gateway keeps the language choice in the accumulated text path.
    parts = parts[1:]
    root = parts[0] if parts else ""

    if root in {"1", "2"} and len(parts) == 2 and parts[1] == "48":
        return _menu_response(TRANSLATIONS[language]["other_location"])
    if root in {"3", "5"} and len(parts) >= 3 and parts[2] == "48":
        if len(parts) == 3:
            return _menu_response(TRANSLATIONS[language]["other_location"])

    location_index = 1 if root in {"1", "2"} else 2 if root in {"3", "5"} else None
    if location_index is not None and len(parts) > location_index + 1 and parts[location_index] == "48":
        custom_location = store.get_location_by_name(parts[location_index + 1])
        if not custom_location:
            return _menu_response(TRANSLATIONS[language]["invalid"], end=True)
        parts = (
            parts[:location_index]
            + [str(custom_location["id"])]
            + parts[location_index + 2:]
        )

    # ---- 1. Find a mechanic: location -> service -> mechanic list ----
    if root == "1":
        if len(parts) == 1:
            return _menu_response(_locations_menu_text(language))

        if len(parts) == 2:
            return _menu_response(_services_menu_text(language))

        if len(parts) == 3:
            location = store.get_location_by_id(parts[1])
            service = store.get_service_by_id(parts[2])
            if not location or not service:
                return _menu_response(TRANSLATIONS[language]["invalid"], end=True)
            mechanics = store.find_mechanics(location["id"], service["id"])
            return _menu_response(_mechanics_list_text(mechanics, location["name"], language))

        if len(parts) == 4:
            location = store.get_location_by_id(parts[1])
            service = store.get_service_by_id(parts[2])
            if not location or not service:
                return _menu_response(TRANSLATIONS[language]["invalid"], end=True)
            mechanics = store.find_mechanics(location["id"], service["id"])
            try:
                chosen = mechanics[int(parts[3]) - 1]
            except (ValueError, IndexError):
                return _menu_response(TRANSLATIONS[language]["invalid_mechanic"], end=True)

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
            return _menu_response(_locations_menu_text(language))

        if len(parts) == 2:
            location = store.get_location_by_id(parts[1])
            if not location:
                return _menu_response("Invalid selection.", end=True)
            mechanics = store.find_mechanics(location["id"], general_service["id"])
            return _menu_response(_mechanics_list_text(mechanics, location["name"], language))

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
            return _menu_response(_services_menu_text(language))

        if len(parts) == 2:
            return _menu_response(_locations_menu_text(language))

        if len(parts) == 3:
            service = store.get_service_by_id(parts[1])
            location = store.get_location_by_id(parts[2])
            if not service or not location:
                return _menu_response("Invalid selection.", end=True)
            mechanics = store.find_mechanics(location["id"], service["id"])
            return _menu_response(_mechanics_list_text(mechanics, location["name"], language))

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
            return _menu_response(_locations_menu_text(language))

        if len(parts) == 3:
            return _menu_response(
                _services_menu_text(language)
                + "\n\n" + TRANSLATIONS[language]["services_hint"]
            )

        if len(parts) == 4:
            return _menu_response(TRANSLATIONS[language]["phone"])

        if len(parts) == 5:
            return _menu_response(TRANSLATIONS[language]["email"])

        if len(parts) == 6:
            try:
                name = parts[1].strip()
                location = store.get_location_by_id(parts[2])
                service_ids = [s.strip() for s in parts[3].split(",") if s.strip()]
                phone = parts[4].strip()
                email = parts[5].strip()
                if (
                    not name
                    or not location
                    or not service_ids
                    or not phone
                    or not re.fullmatch(r"\+?\d{9,15}", phone)
                    or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)
                ):
                    raise ValueError
                if any(store.get_service_by_id(service_id) is None for service_id in service_ids):
                    raise ValueError
            except (TypeError, ValueError):
                return _menu_response(TRANSLATIONS[language]["invalid"], end=True)

            try:
                mechanic = store.register_mechanic(
                    name=name,
                    phone=phone,
                    email=email,
                    location_id=location["id"],
                    service_ids=service_ids,
                )
            except Exception as exc:  # noqa: BLE001
                print("Mechanic registration failed:", exc)
                return _menu_response(
                    "Registration could not be completed. Please try again.",
                    end=True,
                )
            return _menu_response(
                f"Registered! Welcome, {mechanic['name']}.\n"
                f"Location: {location['name']}\n"
                "You'll receive breakdown requests by SMS.",
                end=True,
            )

    # ---- Fallback -----------------------------------------------------
    return _menu_response("Invalid option. Please try again.", end=True)
