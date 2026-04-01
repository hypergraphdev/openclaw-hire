# OpenClaw Hire Console

[中文文档](README_CN.md) | English

A self-hosted web console for deploying and managing AI agent instances. Supports [OpenClaw](https://github.com/openclaw/openclaw) and [Zylos](https://github.com/zylos-ai/zylos-core) products with real-time chat, organization management, and plugin marketplace.

## Features

### Instance Management
- **Full Lifecycle** — Create, install, start, stop, restart, upgrade, and uninstall AI agent instances via Docker Compose
- **Self-Check & Repair** — 7-point automatic diagnostics (container, DB, API keys, HXA config, WebSocket, npm deps, AI runtime) with one-click repair. Hub consistency verification ensures org_id/agent_name stay in sync across DB, container config, and Hub API
- **File Browser** — Browse container file system, download files directly from the web UI
- **Docker Control** — View container logs, set CPU/memory limits, manage container lifecycle from admin panel

### Communication Channels
- **Real-time Chat** — Talk to your AI agents through HXA Connect (WebSocket-based) with message copy support
- **WeChat Integration** — Connect instances to WeChat via QR code login. Messages flow through the C4 comm-bridge with automatic deduplication
- **Telegram Integration** — Bind Telegram bots to instances for mobile access
- **HXA Organization** — Multi-org bot communication hub. Bots can be transferred between organizations. Each user gets a dedicated admin bot per org for DM conversations

### Plugin Marketplace
- **One-click Install** — Install plugins directly into running containers
- **Available Plugins** — WeChat (zylos-weixin), Whisper STT (speech-to-text), Edge-TTS (text-to-speech)
- **WSL/Docker Compatible** — Handles permission quirks on WSL2 Docker automatically

### Administration
- **Global Settings** — Configure default AI model, API keys (Anthropic/OpenAI), HXA Hub connection from a single panel
- **Configurable AI Model** — Set default model for new instances (e.g. `claude-sonnet-4-5`, `claude-opus-4`, or any compatible model)
- **User Management** — First registered user becomes admin automatically. View and manage all users
- **HXA Org Management** — Create/delete organizations, manage agents, rotate secrets, transfer bots between orgs
- **Instance Diagnostics** — Per-instance health checks including HXA/Telegram/Claude/container status
- **i18n** — Full English and Chinese interface

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

### System Architecture

```mermaid
graph TB
    subgraph Client["Client Layer"]
        Browser["Browser"]
        WeChat["WeChat App"]
        Telegram["Telegram App"]
    end

    subgraph Console["OpenClaw Hire Console"]
        Frontend["Frontend<br/>React 19 + Vite 7 + Tailwind"]
        Backend["Backend<br/>FastAPI + JWT Auth"]
        MySQL[("MySQL<br/>Users, Instances,<br/>Configs, Settings")]
    end

    subgraph Hub["HXA Connect Hub"]
        HubAPI["REST API + WebSocket"]
        OrgMgmt["Organization Manager"]
    end

    subgraph Instances["AI Agent Instances (Docker)"]
        OC["OpenClaw Container<br/>Gateway + CLI"]
        ZY["Zylos Container<br/>Claude/Codex Runtime"]
        HXAPlugin["HXA Connect Plugin"]
        TGPlugin["Telegram Plugin"]
        WXPlugin["WeChat Plugin"]
        C4["C4 Comm-Bridge"]
    end

    Browser -->|HTTPS| Frontend
    Frontend -->|REST API| Backend
    Backend --> MySQL
    Backend -->|Docker API| Instances
    Backend -->|REST + WS| Hub

    Hub <-->|WebSocket| HXAPlugin
    WeChat <-->|Long Poll| WXPlugin
    Telegram <-->|Bot API| TGPlugin

    WXPlugin -->|C4 receive| C4
    TGPlugin -->|C4 receive| C4
    HXAPlugin -->|C4 receive| C4
    C4 -->|tmux paste| OC
    C4 -->|tmux paste| ZY
    OC -->|C4 send| C4
    ZY -->|C4 send| C4

    style Console fill:#1a1a2e,stroke:#16213e,color:#fff
    style Hub fill:#0f3460,stroke:#16213e,color:#fff
    style Instances fill:#1a1a2e,stroke:#533483,color:#fff
    style Client fill:#1a1a2e,stroke:#16213e,color:#fff
```

### Module Structure

```mermaid
graph TB
    subgraph FE["Frontend Modules"]
        direction LR
        Dashboard["Dashboard"]
        InstDetail["Instance Detail"]
        Marketplace["Marketplace"]
        MyOrg["My Org"]
        Admin["Admin"]
        Settings["Settings"]
    end

    subgraph BE["Backend Routes"]
        direction LR
        AuthRoute["auth"]
        InstRoute["instances"]
        OrgRoute["my_org"]
        AdminRoute["admin"]
        HXARoute["admin_hxa"]
        SettingsRoute["settings"]
        MktRoute["marketplace"]
    end

    subgraph Services["Backend Services"]
        direction LR
        InstallSvc["install_service"]
        AuthSvc["auth_service"]
        DB["database"]
        MsgIdx["message_index"]
    end

    FE -->|REST API| BE
    BE --> Services

    style FE fill:#1a1a2e,stroke:#e94560,color:#fff
    style BE fill:#1a1a2e,stroke:#0f3460,color:#fff
    style Services fill:#1a1a2e,stroke:#533483,color:#fff
```

### Instance Install Flow

```mermaid
sequenceDiagram
    participant U as User
    participant FE as Frontend
    participant BE as Backend
    participant D as Docker
    participant Hub as HXA Hub

    U->>FE: Click "Install"
    FE->>BE: POST /instances/{id}/install
    BE->>BE: Clone product repo
    BE->>BE: Find compose file
    BE->>D: docker compose up -d --build
    D-->>BE: Container running
    BE->>BE: Inject API keys from global settings
    BE->>Hub: Register agent in org
    Hub-->>BE: bot_token + agent_id
    BE->>D: Write HXA config to container
    BE->>D: Restart HXA plugin
    BE-->>FE: Install complete
    FE-->>U: Status: Running
```

### Message Flow (WeChat Example)

```mermaid
sequenceDiagram
    participant WX as WeChat User
    participant Bot as WeChat Plugin
    participant C4R as C4 Receive
    participant C4D as C4 Dispatcher
    participant AI as Claude (tmux)
    participant C4S as C4 Send
    participant Adapter as send.js Adapter

    WX->>Bot: Send message
    Bot->>Bot: Dedup check (30s window)
    Bot->>C4R: node c4-receive.js --channel weixin
    C4R->>C4R: Append "reply via" suffix
    C4R->>C4D: Queue in SQLite
    C4D->>AI: Paste to tmux session
    AI->>AI: Process message
    AI->>C4S: node c4-send.js "weixin" "endpoint"
    C4S->>Adapter: node scripts/send.js endpoint message
    Adapter->>Adapter: Translate positional → named args
    Adapter->>Bot: node dist/scripts/send.js --endpoint --content
    Bot->>WX: Send reply via WeChat API
```

**Tech Stack:**
- **Frontend:** React 19 + Vite 7 + TypeScript + Tailwind CSS
- **Backend:** FastAPI + MySQL (mysql-connector-python)
- **Auth:** JWT (HS256, 7-day expiry) + PBKDF2-SHA256 password hashing
- **Messaging:** HXA Connect Hub (WebSocket)
- **Containers:** Docker Compose for AI agent instances
- **Deployment:** Nginx reverse proxy, Docker Compose for self-hosting

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
