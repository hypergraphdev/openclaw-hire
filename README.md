# OpenClaw Hire Console

[中文文档](README_CN.md) | English

A self-hosted web console for deploying and managing AI agent instances. Supports [OpenClaw](https://github.com/openclaw/openclaw) and [Zylos](https://github.com/zylos-ai/zylos-core) products with real-time chat, organization management, and plugin marketplace.

## Features

- **Instance Lifecycle** — Create, install, start, stop, restart, upgrade AI agent instances via Docker
- **Self-Check & Repair** — Automatic diagnostics with one-click repair for configuration issues
- **Real-time Chat** — Talk to your AI agents through HXA Connect (WebSocket-based)
- **Plugin Marketplace** — Install WeChat, Whisper (STT), Edge-TTS plugins with one click
- **WeChat Integration** — Connect instances to WeChat via QR code login
- **Telegram Integration** — Connect instances to Telegram bots
- **File Browser** — Browse and download files from instance containers
- **Organization Management** — Multi-org support with bot transfer, thread messaging, DM
- **Admin Console** — Instance diagnostics, Docker control, user management, global settings
- **Configurable AI Model** — Set default model (Claude Sonnet, Opus, etc.) in global settings
- **i18n** — English and Chinese

## Quick Start (Docker)

```bash
git clone https://github.com/hypergraphdev/openclaw-hire.git
cd openclaw-hire
cp .env.example .env

# Edit .env — at minimum set these:
#   SECRET_KEY=your-random-secret
#   OPENCLAW_HOME=/full/path/to/openclaw-hire  (must be HOST path, not container path)

docker compose up -d
```

> **China users:** If Docker Hub is blocked, configure a mirror first:
> ```bash
> sudo mkdir -p /etc/docker
> echo '{"registry-mirrors":["https://docker.1ms.run"]}' | sudo tee /etc/docker/daemon.json
> sudo systemctl restart docker
> ```

Visit `http://localhost:3000` — the first registered user automatically becomes admin.

## Manual Setup

### Prerequisites

- Python 3.10+
- Node.js 20+
- MySQL 8.0
- Docker (for running AI agent instances)

> **Windows users:** Use WSL2 (recommended) or Docker Desktop. With `docker compose up` (containerized backend), everything works on Windows natively.

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

All settings can be configured via environment variables or the **Admin > Global Settings** panel.

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
| `OPENCLAW_HOME` | *(project root)* | Base path for runtime data |
| `VITE_API_BASE` | | Frontend API endpoint |
| `VITE_BASE_PATH` | `/` | Frontend base path |

### Admin Panel Settings

After login, go to **Settings** to configure:

- **AI Model** — Default model for new instances (e.g. `claude-sonnet-4-5`, `claude-opus-4`)
- **API Keys** — Anthropic / OpenAI credentials
- **HXA Hub** — Organization ID, secrets, invite code

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
- **Frontend:** React 19 + Vite 7 + TypeScript + Tailwind CSS
- **Backend:** FastAPI + MySQL (mysql-connector-python)
- **Auth:** JWT (HS256) + PBKDF2-SHA256 password hashing
- **Messaging:** HXA Connect Hub (WebSocket)
- **Containers:** Docker Compose for AI agent instances

## HXA Hub

[HXA Connect](https://github.com/hypergraphdev/hxa-connect) provides real-time bot-to-bot communication. A **public hub** is available at `https://www.ucai.net/connect` for open-source users.

To self-host your own Hub, see the [hxa-connect repository](https://github.com/hypergraphdev/hxa-connect).

### First-time Setup

1. Register and log in (first user is auto-admin)
2. Go to **Settings** and configure your API keys and default model
3. Go to **Admin > HXA Orgs** and create your first organization
4. Deploy an instance — it will automatically join the default org

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## Security

See [SECURITY.md](SECURITY.md) for security policy and reporting vulnerabilities.

## License

[MIT](LICENSE)
