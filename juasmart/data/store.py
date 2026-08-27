"""
JuaSmart in-memory data store.

This is intentionally a plain Python module with module-level lists acting
as "tables". Swap this out for a real database (Postgres via SQLAlchemy,
etc.) in production — routes only ever call the functions below, so the
internals here can be replaced without touching route code.
"""

import math
import uuid
from datetime import datetime

# ---- Reference data ------------------------------------------------------

LOCATIONS = [
    {"id": 1, "name": "Kiambu Town", "lat": -1.1714, "lng": 36.8356},
    {"id": 2, "name": "Ruaka", "lat": -1.2033, "lng": 36.7833},
    {"id": 3, "name": "Ruiru", "lat": -1.1495, "lng": 36.9622},
    {"id": 4, "name": "Thika", "lat": -1.0388, "lng": 37.0834},
]

SERVICES = [
    {"id": 1, "name": "Engine problem"},
    {"id": 2, "name": "Flat tyre"},
    {"id": 3, "name": "Battery"},
    {"id": 4, "name": "Electrical"},
    {"id": 5, "name": "Towing"},
    {"id": 6, "name": "General repair"},
]

# ---- Mechanics -------------------------------------------------------
# Seeded with sample mechanics so the demo works out of the box.

MECHANICS = [
    {
        "id": "m1",
        "name": "Mike Auto Garage",
        "phone": "+254708362216",
        "location_id": 1,
        "lat": -1.1745,
        "lng": 36.8340,
        "services": [1, 3, 6],
        "available": True,
    },
    {
        "id": "m2",
        "name": "John Motors",
        "phone": "+254700333444",
        "location_id": 1,
        "lat": -1.1600,
        "lng": 36.8400,
        "services": [2, 4, 5],
        "available": True,
    },
    {
        "id": "m3",
        "name": "Wanjiku Auto Care",
        "phone": "+254700555666",
        "location_id": 1,
        "lat": -1.1900,
        "lng": 36.8500,
        "services": [3, 6],
        "available": True,
    },
    {
        "id": "m4",
        "name": "Ruaka Quick Fix",
        "phone": "+254700777888",
        "location_id": 2,
        "lat": -1.2050,
        "lng": 36.7800,
        "services": [1, 2, 3, 4, 5, 6],
        "available": True,
    },
]

# ---- Requests (breakdown dispatch tickets) --------------------------

REQUESTS = []
CUSTOM_LOCATIONS = []


# ---- Helpers ----------------------------------------------------------

def distance_km(lat1, lng1, lat2, lng2):
    """Haversine distance in kilometers between two lat/lng points."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(d_lng / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def get_locations():
    return LOCATIONS


def get_services():
    return SERVICES


def get_location_by_id(location_id):
    location_id = int(location_id)
    return next(
        (location for location in LOCATIONS + CUSTOM_LOCATIONS if location["id"] == location_id),
        None,
    )


def get_location_by_name(name):
    normalized_name = name.strip().casefold()
    location = next(
        (location for location in LOCATIONS + CUSTOM_LOCATIONS
         if location["name"].casefold() == normalized_name),
        None,
    )
    if location or not normalized_name:
        return location
    location = {
        "id": max([48] + [item["id"] for item in CUSTOM_LOCATIONS]) + 1,
        "name": name.strip(),
        "lat": 0,
        "lng": 0,
    }
    CUSTOM_LOCATIONS.append(location)
    return location


def get_service_by_id(service_id):
    return next((s for s in SERVICES if s["id"] == int(service_id)), None)


def get_mechanic_by_id(mechanic_id):
    return next((m for m in MECHANICS if m["id"] == mechanic_id), None)


def get_mechanic_by_phone(phone):
    target = _normalize_phone(phone)
    return next(
        (mechanic for mechanic in MECHANICS if _normalize_phone(mechanic["phone"]) == target),
        None,
    )


def get_requests_for_mechanic(mechanic_id):
    return [request for request in REQUESTS if request["mechanic_id"] == mechanic_id]


def find_mechanics(location_id, service_id):
    """Available mechanics offering a service, sorted nearest-first."""
    location = get_location_by_id(location_id)
    if not location:
        return []

    matches = []
    for m in MECHANICS:
        if (
            m["available"]
            and m["location_id"] == location["id"]
            and int(service_id) in m["services"]
        ):
            d = distance_km(location["lat"], location["lng"], m["lat"], m["lng"])
            matches.append({**m, "distance_km": round(d, 1)})

    matches.sort(key=lambda m: m["distance_km"])
    return matches


def register_mechanic(name, phone, email, location_id, service_ids):
    location = get_location_by_id(location_id)
    mechanic = {
        "id": str(uuid.uuid4()),
        "name": name,
        "phone": _normalize_phone(phone),
        "email": email,
        "location_id": int(location_id),
        "lat": location["lat"] if location else 0,
        "lng": location["lng"] if location else 0,
        "services": [int(s) for s in service_ids],
        "available": True,
    }
    MECHANICS.append(mechanic)
    return mechanic


def _normalize_phone(phone):
    """Keep phone matching consistent with utils.sms.normalize_phone."""
    if not phone:
        return ""
    digits = "".join(c for c in str(phone) if c.isdigit())
    if digits.startswith("0") and len(digits) >= 10:
        digits = "254" + digits[1:]
    elif len(digits) == 9 and digits.startswith("7"):
        digits = "254" + digits
    if digits.startswith("254"):
        return f"+{digits}"
    return str(phone).strip()


def create_request(driver_phone, mechanic_id, location_id, service_id):
    req = {
        "id": str(uuid.uuid4())[:8],  # short ID, easy to read back in an SMS
        "driver_phone": _normalize_phone(driver_phone),
        "mechanic_id": mechanic_id,
        "location_id": int(location_id),
        "service_id": int(service_id),
        "status": "PENDING",  # PENDING -> ACCEPTED | DECLINED
        "created_at": datetime.utcnow().isoformat(),
    }
    REQUESTS.append(req)
    return req


def get_request_by_id(request_id):
    return next((r for r in REQUESTS if r["id"] == request_id), None)


def get_pending_request_for_mechanic(mechanic_phone):
    """Most recent pending request addressed to this mechanic's phone."""
    target = _normalize_phone(mechanic_phone)
    candidates = [
        r
        for r in REQUESTS
        if r["status"] == "PENDING"
        and get_mechanic_by_id(r["mechanic_id"])
        and _normalize_phone(get_mechanic_by_id(r["mechanic_id"])["phone"]) == target
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda r: r["created_at"], reverse=True)[0]


def update_request_status(request_id, status):
    req = get_request_by_id(request_id)
    if req:
        req["status"] = status
    return req
