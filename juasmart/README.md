# JuaSmart — USSD Emergency Mechanic Dispatch Platform

A USSD + SMS platform that connects drivers with nearby available mechanics
during a breakdown — no smartphone or internet required. Built on Flask,
designed to run behind Africa's Talking's USSD and SMS gateways, and ready
to deploy on Render.

## How it works

1. Driver dials a shortcode (e.g. `*384*1234#` in sandbox, or your assigned
   code in production).
2. The USSD menu lets them find a mechanic by location + service needed.
3. JuaSmart matches available, nearby mechanics (sorted by distance) and
   the driver picks one.
4. The mechanic gets an SMS with the job details and replies **YES**/**NO**.
5. The driver gets an SMS the moment the mechanic accepts (or a nudge to
   try another garage if they decline).

## Project structure

```
juasmart_flask/
├── app.py                # Flask entrypoint + health/debug routes
├── routes/
│   ├── ussd.py            # USSD menu state machine
│   └── sms.py              # Inbound SMS webhook (accept/decline)
├── data/
│   └── store.py            # In-memory data (swap for a real DB later)
├── utils/
│   └── sms.py               # Africa's Talking SMS wrapper (with dry-run mode)
├── requirements.txt
├── Procfile                 # Render/Heroku start command
├── render.yaml               # Optional one-click Render config
└── .env.example
```

## Local setup

```bash
git clone <your-repo-url>
cd juasmart_flask
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
flask --app app run --debug
```

By default `SMS_DRY_RUN=true`, so outgoing SMS just print to your terminal —
you can build and test the entire flow with zero Africa's Talking setup.

## Testing the USSD flow locally (without a real USSD gateway)

Africa's Talking just POSTs form data to your `/ussd` endpoint. You can
simulate a full session with curl by sending the accumulated `text`:

```bash
# Step 1: root menu
curl -X POST http://localhost:5000/ussd \
  -d "sessionId=1" -d "phoneNumber=+254700999888" -d "text="

# Step 2: choose "1" (English)
curl -X POST http://localhost:5000/ussd \
  -d "sessionId=1" -d "phoneNumber=+254700999888" -d "text=1"

# Step 3: choose "1" (Find a mechanic)
curl -X POST http://localhost:5000/ussd \
  -d "sessionId=1" -d "phoneNumber=+254700999888" -d "text=1*1"

# Step 4: choose location 1 (Kiambu Town)
curl -X POST http://localhost:5000/ussd \
  -d "sessionId=1" -d "phoneNumber=+254700999888" -d "text=1*1*1"

# Step 5: choose service 3 (Battery)
curl -X POST http://localhost:5000/ussd \
  -d "sessionId=1" -d "phoneNumber=+254700999888" -d "text=1*1*1*3"

# Step 6: choose mechanic 1 from the returned list
curl -X POST http://localhost:5000/ussd \
  -d "sessionId=1" -d "phoneNumber=+254700999888" -d "text=1*1*1*3*1"
```

Then simulate the mechanic accepting via the SMS webhook:

```bash
curl -X POST http://localhost:5000/sms/inbound \
  -d "from=+254700111222" -d "text=YES"
```

Check `/debug/requests` to see the request status flip to `ACCEPTED`.

## Debug endpoints

- `GET /debug/mechanics` — list all mechanics (including newly registered ones)
- `GET /debug/requests` — list all breakdown requests and their status
- `GET /debug/locations` / `GET /debug/services` — reference data
- `GET /debug/sms` — recent outgoing SMS attempts and delivery status

SMS attempts are stored in SQLite at `SMS_DB_PATH`, defaulting to
`sms_logs.db`. For Render, attach a persistent disk mounted at `/var/data`
so the configured `/var/data/sms_logs.db` survives restarts and deploys.

## Deploying to Render

1. Push this project to a GitHub repo.
2. On Render: **New → Web Service**, connect the repo.
3. Render will detect `render.yaml` automatically (or set manually):
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn app:app`
4. In the Render dashboard, set environment variables:
   - `AT_USERNAME`, `AT_API_KEY`, `AT_SHORTCODE` — from your Africa's Talking account
   - `SMS_DRY_RUN=false` once you're ready to send real SMS
5. Deploy. Render gives you a public URL like
   `https://juasmart-ussd-api.onrender.com`.
6. In the Africa's Talking dashboard, set your **USSD callback URL** to
   `https://juasmart-ussd-api.onrender.com/ussd` and your **SMS callback
   URL** to `https://juasmart-ussd-api.onrender.com/sms/inbound`.

## Next steps (production hardening)

- Replace `data/store.py` with a real database (Postgres is a good fit on
  Render) — the function signatures are already the seam to swap it in.
- Add a mechanic "available/busy" toggle via USSD.
- Auto-fallback to the next-nearest mechanic if the first declines or
  times out.
- Add basic auth/signature verification on the webhook routes.
