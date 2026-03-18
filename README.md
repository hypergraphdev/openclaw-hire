# OpenClaw Hire

This is the OpenClaw Hire multipage control-console implementation.

It includes:

- FastAPI backend with SQLite persistence (Python)
- Vite + React frontend + Tailwind CSS
- Multi-page dashboard with account, templates, fleet, agent detail, and settings
- End-to-end initialization timeline tracking for each AI agent
- Async-style backend state progression for provisioning workflow
- Hire-time stack selection: OpenClaw or Zylos
- Docker-based install flow for both stacks after hiring

## Features

### Backend APIs

- `POST /api/register`
- `GET /api/templates`
- `POST /api/employees` (supports `stack: openclaw | zylos`)
- `GET /api/owners/{owner_id}/employees`
- `GET /api/employees/{employee_id}/status`
- `POST /api/employees/{employee_id}/bot-token`
- `GET /api/dashboard/{owner_id}`

### Frontend pages (now multi-page)

- `Dashboard` (`/dashboard`)
- `Settings / Profile` (`/settings`)
- `Create Agent` (`/agents/new`)
- `Agent Fleet` (`/agents`)
- `Agent Detail` (`/agents/:employeeId`)
- `Templates` (`/templates`)

Default employee model config:

- `openai-codex/gpt-5.3-codex-spark`

Stack options for hire:

- `openclaw` -> `https://github.com/openclaw/openclaw`
- `zylos` -> `https://github.com/zylos-ai/zylos-core`
- Both are provisioned through Docker-oriented workflow messages/states.

Initialization states tracked:

- `queued`
- `preparing_workspace`
- `writing_config`
- `creating_service`
- `waiting_bot_token`
- `ready`
- `failed`

## Local run

Backend:

```bash
cd /home/wwwroot/openclaw-hire/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python server.py
```

Frontend:

```bash
cd /home/wwwroot/openclaw-hire/frontend
npm install
npm run dev
```

Frontend defaults to `http://127.0.0.1:8010` for the API. Override with:

```bash
VITE_API_BASE=https://your-host.example.com/openclaw npm run dev
```

## Build commands

Backend production-style run:

```bash
cd /home/wwwroot/openclaw-hire/backend
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8010
```

Frontend production build:

```bash
cd /home/wwwroot/openclaw-hire/frontend
npm install
VITE_BASE_PATH=/openclaw/ npm run build
```

## Deployment notes

Intended public paths:

- `www.ucai.net/openclaw` -> OpenClaw Hire app
- `www.ucai.net/connect` -> HXA-Connect app from `/home/wwwroot/connect`

Suggested mapping:

- reverse proxy `www.ucai.net/openclaw/api/*` to FastAPI on port `8010`
- serve the built Vite app at `www.ucai.net/openclaw` with `VITE_BASE_PATH=/openclaw/`
- reverse proxy `www.ucai.net/connect` to the existing HXA-Connect deployment with base path enabled

If you deploy the frontend under `/openclaw`, build it with a matching Vite base path strategy before publishing static assets.

## Bootstrap template

See [BOOTSTRAP_TEMPLATE.md](/home/wwwroot/openclaw-hire/BOOTSTRAP_TEMPLATE.md) for the intended security-auditor style clone flow.
