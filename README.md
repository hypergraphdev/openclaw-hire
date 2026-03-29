# OpenClaw Hire Console

A self-hosted web console for deploying and managing AI agent instances. Supports [OpenClaw](https://github.com/nicepkg/openclaw) and [Zylos](https://github.com/nicepkg/zylos) products with real-time chat, organization management, and plugin marketplace.

## Features

- **Instance Lifecycle** — Create, install, start, stop, restart, upgrade AI agent instances via Docker
- **Real-time Chat** — Talk to your AI agents through HXA Connect (WebSocket-based)
- **Plugin Marketplace** — Install WeChat, Whisper (STT), Edge-TTS plugins with one click
- **File Browser** — Browse and download files from instance containers
- **Organization Management** — Multi-org support with bot transfer, thread messaging
- **Telegram Integration** — Connect instances to Telegram bots
- **Admin Console** — Instance diagnostics, Docker management, user management, global settings
- **i18n** — English and Chinese

## Quick Start (Docker)

```bash
git clone https://github.com/nicepkg/openclaw-hire.git
cd openclaw-hire
cp .env.example .env
# Edit .env with your settings (SECRET_KEY is required)
docker compose up -d
```

Visit `http://localhost:3000` — register an account and start deploying AI agents.

## Manual Setup

### Prerequisites

- Python 3.10+
- Node.js 20+
- MySQL 8.0
- Docker (for running AI agent instances)

> **Windows users:** Use WSL2 (recommended) or Docker Desktop. The instance install scripts require a Linux/macOS shell. With `docker compose up` (containerized backend), everything works on Windows natively.

### Backend

```bash
cd backend
pip install -r requirements.txt
cp ../.env.example ../.env
# Edit ../.env

uvicorn app.main:app --reload --port 8012
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Database

Create a MySQL database and user:

```sql
CREATE DATABASE openclaw_hire CHARACTER SET utf8mb4;
CREATE USER 'openclaw'@'localhost' IDENTIFIED BY 'your-password';
GRANT ALL ON openclaw_hire.* TO 'openclaw'@'localhost';
```

Tables are auto-created on first startup.

## Configuration

All settings can be configured via environment variables or the admin settings panel.

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | *(required)* | JWT signing key |
| `DB_HOST` | `localhost` | MySQL host |
| `DB_NAME` | `openclaw_hire` | MySQL database name |
| `DB_USER` | `openclaw` | MySQL user |
| `DB_PASSWORD` | | MySQL password |
| `SITE_BASE_URL` | `https://www.ucai.net` | Public URL for your deployment |
| `HXA_HUB_URL` | `https://www.ucai.net/connect` | HXA Connect Hub (public hub available) |
| `ANTHROPIC_BASE_URL` | | Anthropic API proxy URL |
| `ANTHROPIC_AUTH_TOKEN` | | Anthropic API key |
| `WHISPER_SERVICE_URL` | `http://172.17.0.1:8019` | Whisper STT service |
| `OPENCLAW_HOME` | *(project root)* | Base path for runtime data |
| `VITE_API_BASE` | | Frontend API endpoint |
| `VITE_BASE_PATH` | `/` | Frontend base path |

See [`.env.example`](.env.example) for a complete template.

## Architecture

```
Browser ──→ Frontend (React/Vite) ──→ Backend (FastAPI)
                                          │
                                          ├──→ MySQL
                                          ├──→ Docker (instance containers)
                                          └──→ HXA Hub (real-time messaging)
                                                  │
                                              WebSocket
```

**Tech Stack:**
- **Frontend:** React 19 + Vite + TypeScript + Tailwind CSS
- **Backend:** FastAPI + MySQL (mysql-connector-python)
- **Messaging:** HXA Connect Hub (WebSocket)
- **Containers:** Docker Compose for AI agent instances

## HXA Hub

[HXA Connect](https://github.com/hypergraphdev/hxa-connect) provides real-time bot-to-bot communication. A **public hub** is available at `https://www.ucai.net/connect` for open-source users.

To self-host your own Hub, see the [hxa-connect repository](https://github.com/hypergraphdev/hxa-connect).

### First-time Setup

1. Register and log in as admin
2. Go to **Admin > Global Settings** and set your Hub URL
3. Go to **Admin > HXA Orgs** and create your first organization
4. Set it as default — new instances will automatically join this org

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## Security

See [SECURITY.md](SECURITY.md) for security policy and reporting vulnerabilities.

## License

[MIT](LICENSE)
