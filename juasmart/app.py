"""
JuaSmart — USSD Emergency Mechanic Dispatch Platform.

Entry point. Wires up the USSD and SMS webhook blueprints, plus a couple
of plain JSON endpoints useful for debugging/demoing without needing an
actual USSD gateway.

Local run:
    flask --app app run --debug

Production (Render uses this via the Procfile / start command):
    gunicorn app:app
"""

import os
from flask import Flask, jsonify, request
from dotenv import load_dotenv

from routes.ussd import ussd_bp
from routes.sms import sms_bp
from data import sms_store, store

load_dotenv()

app = Flask(__name__)
app.register_blueprint(ussd_bp)
app.register_blueprint(sms_bp)


@app.route("/", methods=["GET"])
def health():
    """Simple health check — also what Render will ping to confirm the
    service is alive."""
    return jsonify({"status": "ok", "service": "JuaSmart USSD API"})


@app.route("/debug/mechanics", methods=["GET"])
def debug_mechanics():
    """List all registered mechanics. Handy for verifying registration
    worked, without needing a database viewer."""
    return jsonify(store.MECHANICS)


@app.route("/debug/requests", methods=["GET"])
def debug_requests():
    """List all breakdown requests and their status."""
    return jsonify(store.REQUESTS)


@app.route("/debug/clients", methods=["GET"])
def debug_clients():
    """List registered client profiles (PINs included for demo only)."""
    return jsonify(store.CLIENTS)


@app.route("/debug/locations", methods=["GET"])
def debug_locations():
    return jsonify(store.LOCATIONS)


@app.route("/debug/services", methods=["GET"])
def debug_services():
    return jsonify(store.SERVICES)


@app.route("/debug/sms", methods=["GET"])
def debug_sms():
    """List recent outgoing SMS attempts."""
    return jsonify(sms_store.get_logs())


@app.route("/admin/sms/logs", methods=["GET"])
def admin_sms_logs():
    direction = request.args.get("direction")
    try:
        limit = min(int(request.args.get("limit", 100)), 500)
    except ValueError:
        limit = 100
    logs = sms_store.get_logs(limit=limit, direction=direction)
    return jsonify({"count": len(logs), "logs": logs})


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
