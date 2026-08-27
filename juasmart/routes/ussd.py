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
from utils.respond import respond_to_request
from utils.sms import normalize_phone, send_sms

ussd_bp = Blueprint("ussd", __name__)
SESSION_LANGUAGES = {}
SESSION_CLIENTS = {}

TRANSLATIONS = {
    "en": {
        "select_location": "Select your location:",
        "service_needed": "What service do you need?",
        "services_offered": "Which services do you offer?",
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
        "mechanic_login": "Mechanic login",
        "client_register": "Client register",
        "client_login": "Client login",
        "login_phone": "Enter your registered phone number:",
        "login_failed": "No mechanic account found for that phone number.",
        "no_pending": "You have no pending requests.",
        "pick_job": "Select a pending request:",
        "respond_prompt": "1. Accept\n2. Decline",
        "invalid_job": "Invalid request selection.",
        "accepted_ok": "Request accepted. Client has been notified by SMS.",
        "declined_ok": "Request declined. Client has been notified by SMS.",
        "client_name": "Enter your full name:",
        "client_pin": "Create a 4-digit PIN:",
        "client_pin_confirm": "Confirm your 4-digit PIN:",
        "client_pin_login": "Enter your 4-digit PIN:",
        "client_pin_mismatch": "PINs do not match. Create a 4-digit PIN:",
        "client_registered": "Account created! You can now log in for named requests.",
        "client_login_ok": "Welcome back, {name}. You are logged in.",
        "client_login_failed": "Incorrect PIN or no client account. Register first.",
        "client_exists": "This phone already has an account. Use Client login.",
        "request_sent": (
            "Request sent to {garage}.\n"
            "Ref: {ref}\n"
            "Check your SMS for confirmation.\n"
            "You'll get another SMS once they respond."
        ),
        "no_requests": "You have no requests yet.",
    },
    "sw": {
        "select_location": "Chagua eneo lako:",
        "service_needed": "Unahitaji huduma gani?",
        "services_offered": "Unatoa huduma gani?",
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
        "mechanic_login": "Kuingia kwa fundi",
        "client_register": "Jisajili kama mteja",
        "client_login": "Kuingia kwa mteja",
        "login_phone": "Ingiza nambari yako ya simu iliyosajiliwa:",
        "login_failed": "Hakuna akaunti ya fundi iliyopatikana kwa nambari hiyo.",
        "no_pending": "Huna maombi yanayosubiri.",
        "pick_job": "Chagua ombi linalosubiri:",
        "respond_prompt": "1. Kubali\n2. Kataa",
        "invalid_job": "Chaguo la ombi si sahihi.",
        "accepted_ok": "Ombi limekubaliwa. Mteja amearifiwa kwa SMS.",
        "declined_ok": "Ombi limekataliwa. Mteja amearifiwa kwa SMS.",
        "client_name": "Ingiza jina lako kamili:",
        "client_pin": "Tengeneza PIN ya tarakimu 4:",
        "client_pin_confirm": "Thibitisha PIN yako ya tarakimu 4:",
        "client_pin_login": "Ingiza PIN yako ya tarakimu 4:",
        "client_pin_mismatch": "PIN hazilingani. Tengeneza PIN ya tarakimu 4:",
        "client_registered": "Akaunti imeundwa! Unaweza kuingia kwa maombi yaliyo na jina.",
        "client_login_ok": "Karibu tena, {name}. Umeingia.",
        "client_login_failed": "PIN si sahihi au hakuna akaunti. Jisajili kwanza.",
        "client_exists": "Simu hii ina akaunti. Tumia kuingia kwa mteja.",
        "request_sent": (
            "Ombi limetumwa kwa {garage}.\n"
            "Ref: {ref}\n"
            "Angalia SMS yako kwa uthibitisho.\n"
            "Utapata SMS nyingine watakapojibu."
        ),
        "no_requests": "Huna maombi bado.",
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
        f"5. {labels['register_mechanic']}\n"
        f"6. {labels['mechanic_login']}\n"
        f"7. {labels['client_register']}\n"
        f"8. {labels['client_login']}"
    )


def _locations_menu_text(language="en"):
    lines = [TRANSLATIONS[language]["select_location"]]
    for loc in store.get_locations():
        if loc["id"] != 5:
            lines.append(f"{loc['id']}. {loc['name']}")
    lines.append("5. Other")
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


def _pending_jobs_text(pending, language="en"):
    labels = TRANSLATIONS[language]
    lines = [labels["pick_job"]]
    for i, item in enumerate(pending, start=1):
        service = store.get_service_by_id(item["service_id"])
        location = store.get_location_by_id(item["location_id"])
        customer = item.get("client_name") or item["driver_phone"]
        service_name = service["name"] if service else "?"
        location_name = location["name"] if location else "?"
        lines.append(
            f"{i}. {item['id']} | {service_name} | {location_name} | {customer}"
        )
    return "\n".join(lines)


def _resolve_client(session_id, driver_phone):
    """Prefer session login, else known profile for this phone."""
    client_id = SESSION_CLIENTS.get(session_id)
    if client_id:
        client = store.get_client_by_id(client_id)
        if client:
            return client
    return store.get_client_by_phone(driver_phone)


def _dispatch_request(driver_phone, mechanic, location, service, session_id=""):
    """
    Create the request, then fire SMS (SokoSure-style USSD → SMS handoff).

    SMS failures are swallowed so the USSD session can still END cleanly.
    """
    driver_phone = normalize_phone(driver_phone)
    client = _resolve_client(session_id, driver_phone)
    req = store.create_request(
        driver_phone=driver_phone,
        mechanic_id=mechanic["id"],
        location_id=location["id"],
        service_id=service["id"],
        client_id=client["id"] if client else None,
        client_name=client["name"] if client else None,
    )
    customer_line = (
        f"Customer: {client['name']} ({driver_phone})"
        if client
        else f"Customer: {driver_phone}"
    )
    mechanic_sms = (
        "NEW BREAKDOWN REQUEST\n"
        f"Ref: {req['id']}\n"
        f"Service: {service['name']}\n"
        f"Location: {location['name']}\n"
        f"{customer_line}\n"
        "Reply YES to ACCEPT or NO to DECLINE\n"
        "Or dial USSD > Mechanic login to respond."
    )
    driver_sms = (
        "JuaSmart: request sent.\n"
        f"Ref: {req['id']}\n"
        f"Garage: {mechanic['name']}\n"
        "You'll get another SMS when they reply YES or NO."
    )
    try:
        send_sms(mechanic["phone"], mechanic_sms)
    except Exception:  # noqa: BLE001
        pass
    try:
        send_sms(driver_phone, driver_sms)
    except Exception:  # noqa: BLE001
        pass
    return req


def _request_sent_response(language, garage, ref):
    return _menu_response(
        TRANSLATIONS[language]["request_sent"].format(garage=garage, ref=ref),
        end=True,
    )


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
            return _menu_response(
                "Choose language / Chagua lugha:\n1. English\n2. Kiswahili",
                end=True,
            )
        language = "en" if root == "1" else "sw"
        SESSION_LANGUAGES[session_id] = language
        return _menu_response(_main_menu_text(language))

    # The gateway keeps the language choice in the accumulated text path.
    parts = parts[1:]
    root = parts[0] if parts else ""

    if root in {"1", "2"} and len(parts) == 2 and parts[1] == "5":
        return _menu_response(TRANSLATIONS[language]["other_location"])
    if root in {"3", "5"} and len(parts) >= 3 and parts[2] == "5":
        if len(parts) == 3:
            return _menu_response(TRANSLATIONS[language]["other_location"])

    location_index = 1 if root in {"1", "2"} else 2 if root in {"3", "5"} else None
    if location_index is not None and len(parts) > location_index + 1 and parts[location_index] == "5":
        custom_location = store.get_location_by_name(parts[location_index + 1])
        if not custom_location:
            return _menu_response(TRANSLATIONS[language]["invalid"], end=True)
        parts = (
            parts[:location_index]
            + [str(custom_location["id"])]
            + parts[location_index + 2:]
        )

    labels = TRANSLATIONS[language]

    # ---- 6. Mechanic login: phone -> pick job -> accept/decline -----
    if root == "6":
        if len(parts) == 1:
            return _menu_response(labels["login_phone"])

        if len(parts) == 2:
            mechanic = store.get_mechanic_by_phone(parts[1])
            if not mechanic:
                return _menu_response(labels["login_failed"], end=True)
            pending = store.get_pending_requests_for_mechanic(mechanic["id"])
            if not pending:
                return _menu_response(
                    f"{labels['welcome']}, {mechanic['name']}.\n"
                    f"{labels['no_pending']}",
                    end=True,
                )
            header = f"{labels['welcome']}, {mechanic['name']}."
            return _menu_response(f"{header}\n{_pending_jobs_text(pending, language)}")

        if len(parts) == 3:
            mechanic = store.get_mechanic_by_phone(parts[1])
            if not mechanic:
                return _menu_response(labels["login_failed"], end=True)
            pending = store.get_pending_requests_for_mechanic(mechanic["id"])
            try:
                chosen = pending[int(parts[2]) - 1]
            except (ValueError, IndexError):
                return _menu_response(labels["invalid_job"], end=True)
            service = store.get_service_by_id(chosen["service_id"])
            location = store.get_location_by_id(chosen["location_id"])
            customer = chosen.get("client_name") or chosen["driver_phone"]
            return _menu_response(
                f"Ref: {chosen['id']}\n"
                f"Service: {service['name'] if service else '?'}\n"
                f"Location: {location['name'] if location else '?'}\n"
                f"Customer: {customer}\n"
                f"{labels['respond_prompt']}"
            )

        if len(parts) == 4:
            mechanic = store.get_mechanic_by_phone(parts[1])
            if not mechanic:
                return _menu_response(labels["login_failed"], end=True)
            pending = store.get_pending_requests_for_mechanic(mechanic["id"])
            try:
                chosen = pending[int(parts[2]) - 1]
            except (ValueError, IndexError):
                return _menu_response(labels["invalid_job"], end=True)
            decision = parts[3]
            if decision == "1":
                ok, _, _ = respond_to_request(chosen, "accept")
                return _menu_response(
                    labels["accepted_ok"] if ok else labels["invalid"],
                    end=True,
                )
            if decision == "2":
                ok, _, _ = respond_to_request(chosen, "decline")
                return _menu_response(
                    labels["declined_ok"] if ok else labels["invalid"],
                    end=True,
                )
            return _menu_response(labels["invalid"], end=True)

        return _menu_response(labels["invalid"], end=True)

    # ---- 7. Client register: name -> pin -> confirm -----------------
    if root == "7":
        if len(parts) == 1:
            existing = store.get_client_by_phone(phone_number)
            if existing:
                return _menu_response(labels["client_exists"], end=True)
            return _menu_response(labels["client_name"])

        if len(parts) == 2:
            return _menu_response(labels["client_pin"])

        if len(parts) == 3:
            pin = parts[2]
            if not pin.isdigit() or len(pin) != 4:
                return _menu_response(labels["invalid"])
            return _menu_response(labels["client_pin_confirm"])

        if len(parts) == 4:
            name = parts[1].strip()
            pin = parts[2]
            confirm = parts[3]
            if not name or not pin.isdigit() or len(pin) != 4:
                return _menu_response(labels["invalid"], end=True)
            if pin != confirm:
                # Keep session open at PIN step conceptually; USSD path is linear
                # so ask them to dial again after mismatch END is clearer.
                return _menu_response(labels["client_pin_mismatch"], end=True)
            client = store.register_client(name=name, phone=phone_number, pin=pin)
            SESSION_CLIENTS[session_id] = client["id"]
            try:
                send_sms(
                    phone_number,
                    (
                        "Welcome to JuaSmart!\n"
                        f"Hi {client['name']},\n"
                        "Your client account is ready. Dial again and log in "
                        "so mechanics see your name on requests."
                    ),
                )
            except Exception:  # noqa: BLE001
                pass
            return _menu_response(labels["client_registered"], end=True)

        return _menu_response(labels["invalid"], end=True)

    # ---- 8. Client login: PIN (phone from AT) ----------------------
    if root == "8":
        if len(parts) == 1:
            return _menu_response(labels["client_pin_login"])

        if len(parts) == 2:
            pin = parts[1]
            client = store.authenticate_client(phone_number, pin)
            if not client:
                return _menu_response(labels["client_login_failed"], end=True)
            SESSION_CLIENTS[session_id] = client["id"]
            return _menu_response(
                labels["client_login_ok"].format(name=client["name"]),
                end=True,
            )

        return _menu_response(labels["invalid"], end=True)

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
                return _menu_response(labels["invalid"], end=True)
            mechanics = store.find_mechanics(location["id"], service["id"])
            return _menu_response(_mechanics_list_text(mechanics, location["name"], language))

        if len(parts) == 4:
            location = store.get_location_by_id(parts[1])
            service = store.get_service_by_id(parts[2])
            if not location or not service:
                return _menu_response(labels["invalid"], end=True)
            mechanics = store.find_mechanics(location["id"], service["id"])
            try:
                chosen = mechanics[int(parts[3]) - 1]
            except (ValueError, IndexError):
                return _menu_response(labels["invalid_mechanic"], end=True)

            req = _dispatch_request(
                phone_number, chosen, location, service, session_id=session_id
            )
            return _request_sent_response(language, chosen["name"], req["id"])

    # ---- 2. Report breakdown: location -> service -> phone -> mechanic
    if root == "2":
        if len(parts) == 1:
            return _menu_response(_locations_menu_text(language))

        if len(parts) == 2:
            location = store.get_location_by_id(parts[1])
            if not location:
                return _menu_response(labels["invalid"], end=True)
            return _menu_response(_services_menu_text(language))

        if len(parts) == 3:
            location = store.get_location_by_id(parts[1])
            service = store.get_service_by_id(parts[2])
            if not location or not service:
                return _menu_response(labels["invalid"], end=True)
            return _menu_response(labels["phone"])

        if len(parts) == 4:
            location = store.get_location_by_id(parts[1])
            service = store.get_service_by_id(parts[2])
            phone = parts[3].strip()
            if not location or not service or not re.fullmatch(r"\+?\d{9,15}", phone):
                return _menu_response(labels["invalid"], end=True)
            mechanics = store.find_mechanics(location["id"], service["id"])
            return _menu_response(_mechanics_list_text(mechanics, location["name"], language))

        if len(parts) == 5:
            location = store.get_location_by_id(parts[1])
            service = store.get_service_by_id(parts[2])
            phone = parts[3].strip()
            if not location or not service or not re.fullmatch(r"\+?\d{9,15}", phone):
                return _menu_response(labels["invalid"], end=True)
            mechanics = store.find_mechanics(location["id"], service["id"])
            try:
                chosen = mechanics[int(parts[4]) - 1]
            except (ValueError, IndexError):
                return _menu_response(labels["invalid_mechanic"], end=True)

            req = _dispatch_request(
                phone, chosen, location, service, session_id=session_id
            )
            return _request_sent_response(language, chosen["name"], req["id"])

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
                return _menu_response(labels["invalid"], end=True)
            mechanics = store.find_mechanics(location["id"], service["id"])
            return _menu_response(_mechanics_list_text(mechanics, location["name"], language))

        if len(parts) == 4:
            service = store.get_service_by_id(parts[1])
            location = store.get_location_by_id(parts[2])
            if not service or not location:
                return _menu_response(labels["invalid"], end=True)
            mechanics = store.find_mechanics(location["id"], service["id"])
            try:
                chosen = mechanics[int(parts[3]) - 1]
            except (ValueError, IndexError):
                return _menu_response(labels["invalid_mechanic"], end=True)

            req = _dispatch_request(
                phone_number, chosen, location, service, session_id=session_id
            )
            return _request_sent_response(language, chosen["name"], req["id"])

    # ---- 4. My requests: show status of latest request ----------------
    if root == "4":
        driver = normalize_phone(phone_number)
        my_requests = [
            r for r in store.REQUESTS if store._normalize_phone(r["driver_phone"]) == driver
        ]
        if not my_requests:
            return _menu_response(labels["no_requests"], end=True)
        latest = sorted(my_requests, key=lambda r: r["created_at"])[-1]
        mechanic = store.get_mechanic_by_id(latest["mechanic_id"])
        client = store.get_client_by_phone(driver)
        name_line = f"Client: {client['name']}\n" if client else ""
        if latest.get("client_name"):
            name_line = f"Client: {latest['client_name']}\n"
        return _menu_response(
            f"{name_line}"
            f"Ref: {latest['id']}\n"
            f"Mechanic: {mechanic['name'] if mechanic else 'Unknown'}\n"
            f"Status: {latest['status']}",
            end=True,
        )

    # ---- 5. Register as mechanic: name -> location -> services -------
    if root == "5":
        if len(parts) == 1:
            return _menu_response(labels["name"])

        if len(parts) == 2:
            return _menu_response(_locations_menu_text(language))

        if len(parts) == 3:
            return _menu_response(
                _services_menu_text(language).replace(
                    labels["service_needed"],
                    labels["services_offered"],
                    1,
                )
                + "\n\n"
                + labels["services_hint"]
            )

        if len(parts) == 4:
            return _menu_response(labels["phone"])

        if len(parts) == 5:
            return _menu_response(labels["email"])

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
                return _menu_response(labels["invalid"], end=True)

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
            service_names = ", ".join(
                store.get_service_by_id(service_id)["name"] for service_id in service_ids
            )
            registration_sms = (
                "JuaSmart: mechanic registration received.\n"
                f"Business: {mechanic['name']}\n"
                f"Location: {location['name']}\n"
                f"Services: {service_names}\n"
                f"Phone: {mechanic['phone']}\n"
                f"Email: {mechanic['email']}"
            )
            try:
                send_sms(mechanic["phone"], registration_sms)
            except Exception as exc:  # noqa: BLE001
                print("Registration SMS failed:", exc)
            return _menu_response(
                f"Registered! Welcome, {mechanic['name']}.\n"
                f"Location: {location['name']}\n"
                "You'll receive breakdown requests by SMS.",
                end=True,
            )

    # ---- Fallback -----------------------------------------------------
    return _menu_response("Invalid option. Please try again.", end=True)
