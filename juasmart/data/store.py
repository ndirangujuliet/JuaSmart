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
    {"id": 1, "name": "Baringo County", "lat": 0.4667, "lng": 35.9667},
    {"id": 2, "name": "Bomet County", "lat": -0.7833, "lng": 35.3417},
    {"id": 3, "name": "Bungoma County", "lat": 0.5635, "lng": 34.5606},
    {"id": 4, "name": "Busia County", "lat": 0.4347, "lng": 34.2422},
    {"id": 5, "name": "Elgeyo-Marakwet County", "lat": 1.0491, "lng": 35.4782},
    {"id": 6, "name": "Embu County", "lat": -0.5391, "lng": 37.4574},
    {"id": 7, "name": "Garissa County", "lat": -0.4532, "lng": 39.6461},
    {"id": 8, "name": "Homa Bay County", "lat": -0.5273, "lng": 34.4571},
    {"id": 9, "name": "Isiolo County", "lat": 0.3546, "lng": 37.5822},
    {"id": 10, "name": "Kajiado County", "lat": -1.8524, "lng": 36.7768},
    {"id": 11, "name": "Kakamega County", "lat": 0.2827, "lng": 34.7519},
    {"id": 12, "name": "Kericho County", "lat": -0.3689, "lng": 35.2863},
    {"id": 13, "name": "Kiambu County", "lat": -1.1714, "lng": 36.8356},
    {"id": 14, "name": "Kilifi County", "lat": -3.6305, "lng": 39.8499},
    {"id": 15, "name": "Kirinyaga County", "lat": -0.6591, "lng": 37.3827},
    {"id": 16, "name": "Kisii County", "lat": -0.6817, "lng": 34.7667},
    {"id": 17, "name": "Kisumu County", "lat": -0.0917, "lng": 34.7680},
    {"id": 18, "name": "Kitui County", "lat": -1.3667, "lng": 38.0106},
    {"id": 19, "name": "Kwale County", "lat": -4.1738, "lng": 39.4521},
    {"id": 20, "name": "Laikipia County", "lat": 0.0167, "lng": 36.9500},
    {"id": 21, "name": "Lamu County", "lat": -2.2717, "lng": 40.9020},
    {"id": 22, "name": "Machakos County", "lat": -1.5177, "lng": 37.2634},
    {"id": 23, "name": "Makueni County", "lat": -1.8039, "lng": 37.6203},
    {"id": 24, "name": "Mandera County", "lat": 3.9366, "lng": 41.8670},
    {"id": 25, "name": "Marsabit County", "lat": 2.3284, "lng": 37.9899},
    {"id": 26, "name": "Meru County", "lat": 0.0463, "lng": 37.6559},
    {"id": 27, "name": "Migori County", "lat": -1.0634, "lng": 34.4731},
    {"id": 28, "name": "Mombasa County", "lat": -4.0435, "lng": 39.6682},
    {"id": 29, "name": "Murang'a County", "lat": -0.7839, "lng": 37.0400},
    {"id": 30, "name": "Nairobi County", "lat": -1.2921, "lng": 36.8219},
    {"id": 31, "name": "Nakuru County", "lat": -0.3031, "lng": 36.0800},
    {"id": 32, "name": "Nandi County", "lat": 0.1833, "lng": 35.1000},
    {"id": 33, "name": "Narok County", "lat": -1.0876, "lng": 35.8711},
    {"id": 34, "name": "Nyamira County", "lat": -0.5633, "lng": 34.9358},
    {"id": 35, "name": "Nyandarua County", "lat": -0.1804, "lng": 36.5220},
    {"id": 36, "name": "Nyeri County", "lat": -0.4167, "lng": 36.9500},
    {"id": 37, "name": "Samburu County", "lat": 1.2150, "lng": 36.9541},
    {"id": 38, "name": "Siaya County", "lat": 0.0612, "lng": 34.2881},
    {"id": 39, "name": "Taita-Taveta County", "lat": -3.3167, "lng": 38.4833},
    {"id": 40, "name": "Tana River County", "lat": -1.5000, "lng": 39.7500},
    {"id": 41, "name": "Tharaka-Nithi County", "lat": -0.3000, "lng": 37.9833},
    {"id": 42, "name": "Trans Nzoia County", "lat": 1.0167, "lng": 35.0000},
    {"id": 43, "name": "Turkana County", "lat": 3.1167, "lng": 35.6000},
    {"id": 44, "name": "Uasin Gishu County", "lat": 0.5143, "lng": 35.2698},
    {"id": 45, "name": "Vihiga County", "lat": 0.0833, "lng": 34.7167},
    {"id": 46, "name": "Wajir County", "lat": 1.7471, "lng": 40.0573},
    {"id": 47, "name": "West Pokot County", "lat": 1.6210, "lng": 35.1199},
    {"id": 48, "name": "Other", "lat": 0, "lng": 0},
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
        "location_id": 13,
        "lat": -1.1745,
        "lng": 36.8340,
        "services": [1, 3, 6],
        "available": True,
    },
    {
        "id": "m2",
        "name": "John Motors",
        "phone": "+254700333444",
        "location_id": 13,
        "lat": -1.1600,
        "lng": 36.8400,
        "services": [2, 4, 5],
        "available": True,
    },
    {
        "id": "m3",
        "name": "Wanjiku Auto Care",
        "phone": "+254700555666",
        "location_id": 13,
        "lat": -1.1900,
        "lng": 36.8500,
        "services": [3, 6],
        "available": True,
    },
    {
        "id": "m4",
        "name": "Ruaka Quick Fix",
        "phone": "+254700777888",
        "location_id": 13,
        "lat": -1.2050,
        "lng": 36.7800,
        "services": [1, 2, 3, 4, 5, 6],
        "available": True,
    },
]

# ---- Requests (breakdown dispatch tickets) --------------------------

REQUESTS = []


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
    return next((l for l in LOCATIONS if l["id"] == int(location_id)), None)


def get_location_by_name(name):
    normalized_name = name.strip().casefold()
    return next(
        (location for location in LOCATIONS if location["name"].casefold() == normalized_name),
        None,
    )


def get_service_by_id(service_id):
    return next((s for s in SERVICES if s["id"] == int(service_id)), None)


def get_mechanic_by_id(mechanic_id):
    return next((m for m in MECHANICS if m["id"] == mechanic_id), None)


def find_mechanics(location_id, service_id):
    """Available mechanics offering a service, sorted nearest-first."""
    location = get_location_by_id(location_id)
    if not location:
        return []

    matches = []
    for m in MECHANICS:
        if m["available"] and int(service_id) in m["services"]:
            d = distance_km(location["lat"], location["lng"], m["lat"], m["lng"])
            matches.append({**m, "distance_km": round(d, 1)})

    matches.sort(key=lambda m: m["distance_km"])
    return matches


def register_mechanic(name, phone, location_id, service_ids):
    location = get_location_by_id(location_id)
    mechanic = {
        "id": str(uuid.uuid4()),
        "name": name,
        "phone": _normalize_phone(phone),
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
