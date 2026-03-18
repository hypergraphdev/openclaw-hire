# OpenClaw Hire Console

Cloud-console style demo for hiring and installing AI products per user account.

## What it does

- User registration + login (email/password)
- Secure password hashing (PBKDF2-SHA256, Python stdlib — no extra deps)
- Authenticated user dashboard
- Product catalog with **two products only**:
  - OpenClaw (`https://github.com/openclaw/openclaw`)
  - Zylos (`https://github.com/zylos-ai/zylos-core`)
- Hire instance into your own account
- Instance list in user control panel
- Click **Install** and watch install progress timeline
- Docker-oriented install semantics in state/events for both products

---

## Architecture

### Backend (`backend/`)

- FastAPI + SQLite
- Modular structure:
  - `app/routes/` → API routers (`auth`, `catalog`, `instances`)
  - `app/services/` → business logic (`auth_service`, `install_service`)
  - `app/deps.py` → auth/database dependencies
  - `app/database.py` → schema + migration-safe setup
  - `app/schemas.py` → Pydantic contracts

### Frontend (`frontend/`)

- React + Vite + Tailwind
- Route guards + auth context
- Pages:
  - `/register`
  - `/login`
  - `/dashboard`
  - `/catalog`
  - `/instances`
  - `/instances/:instanceId`

---

## API overview

### Auth

- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/auth/me`

### Catalog

- `GET /api/catalog`

### Instances (auth required)

- `POST /api/instances` (hire)
- `GET /api/instances` (my list)
- `GET /api/instances/{instance_id}` (detail + timeline)
- `POST /api/instances/{instance_id}/install` (trigger install)

---

## Install progress states

Example progression:

- `idle`
- `pulling`
- `configuring`
- `starting`
- `running` (success)
- `failed` (on error)

Timeline events are persisted and shown in instance detail page.

---

## Local run

### Backend

```bash
cd /home/wwwroot/openclaw-hire/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Required for auto org-join during Telegram configuration
export HXA_CONNECT_ORG_SECRET="<org_secret>"
uvicorn app.main:app --host 0.0.0.0 --port 8010
```

### Frontend

```bash
cd /home/wwwroot/openclaw-hire/frontend
npm install
npm run dev
```

Default API base in dev: `http://127.0.0.1:8010`

---

## Build checks

```bash
cd /home/wwwroot/openclaw-hire/backend
python3 -m compileall app

cd /home/wwwroot/openclaw-hire/frontend
npm run build
```

---

## Notes

- Existing database is migration-tolerant (adds new tables/columns when missing).
- Telegram configuration is now bootstrap-oriented for Zylos instances: user provides only `telegram_bot_token`, and backend auto-injects org/hub/plugin settings and starts `hxa-connect` + `telegram` components.
- `HXA_CONNECT_ORG_SECRET` must be present in backend process env for automatic organization registration.
- One running instance must use one unique Telegram bot token (duplicate token is rejected to avoid Telegram `409 getUpdates` conflicts).
