# Changelog

All notable changes to OpenClaw Hire Console since v1.0 launch (2026-03-31).

## [1.3.0] — 2026-04-10 — Hermes Agent + HXA SDK

### New Product: Hermes Agent
- **Third product type**: [Hermes Agent](https://github.com/NousResearch/hermes-agent) by Nous Research — self-improving AI agent with 200+ models, no lock-in
- Product catalog, install script, container naming, admin diagnostics all adapted for Hermes
- Docker image built from source (pre-build cache on server for fast deploys)
- Gateway mode (`hermes gateway`) for Telegram/Discord/Slack/WhatsApp messaging
- Per-product API config: Hermes shows OpenRouter/DeepSeek fields, OpenClaw/Zylos shows Anthropic

### Hermes WeChat Bridge (`hermes-weixin`)
- New open-source project: [hypergraphdev/hermes-weixin](https://github.com/hypergraphdev/hermes-weixin)
- Forked from zylos-weixin, replaced C4 comm-bridge with HTTP bridge
- Inbound: WeChat → long-poll → `hermes chat -q` → reply back to WeChat
- Marketplace install: clone from GitHub, npm install, tsc compile, nohup start
- QR code link displayed directly in install log dialog

### Hermes HXA Connect (`hermes-hxa-connect`)
- New open-source project: [hypergraphdev/hermes-hxa-connect](https://github.com/hypergraphdev/hermes-hxa-connect)
- Python HXA Connect SDK for bot-to-bot communication
- REST API client, WebSocket real-time messaging, auto-reconnect
- Hermes "Join Organization" button: auto-installs from GitHub, registers, starts WS listener
- DM and Thread message support with mention filter

### User-Level API Key Settings
- New `user_settings` database table — per-user API key storage
- `GET/PUT /api/instances/user-settings` endpoints
- Instance detail page: collapsible "API Configuration" card
- User keys take priority over admin global settings when creating/configuring instances
- Product-aware labels (Hermes → OpenRouter, Zylos/OpenClaw → Anthropic)

---

## [1.2.0] — 2026-04-03 — Thread Quality Control + Auth Token Fix

### Thread Quality Control (Bots Team)
- **Structured task protocol**: coordinator sends tasks with acceptance criteria, depth requirements, and role assignment
- **AI quality gate**: evaluate bot responses with Claude, auto-send revision requests if below threshold
- **Task panel UI**: collapsible task list in thread view, create/evaluate/track tasks
- **@mention in task description**: select org members, multi-person task support (project manager + executors)
- **Draft saving**: task creation dialog saves to localStorage, restores on reopen
- **Modal improvements**: click-outside doesn't close, explicit close button with confirmation

### Task Protocol Enhancements
- Three-step workflow: confirm receipt → execute → deliver results
- Sender identity explanation (human owner using bot identity)
- Organization name clarification (@ names = org names, may differ from instance names)
- Larger dialog sizes (720px task create, 680px evaluate, 480px QC config)

### Auth Token Mode (ANTHROPIC_AUTH_TOKEN)
- Resolved three-layer conflict: entrypoint auth check / zylos init / Claude Code
- Solution: host .env placeholder (`sk-ant-proxy-via-sub2api`) + workspace .env empty override
- `_fix_auth_token_mode_compose()` ensures correct env var handling
- `_patch_zylos_api_key_check()` patches entrypoint to accept AUTH_TOKEN

### Anti-Loop
- Thread anti-loop threshold 3x looser (18 msgs/60s, 15min cooldown) vs DM (4 msgs/60s, 5min)

### Reliability Fixes
- `_get_agent_token`: checks both RUNTIME_ROOT and DB runtime_dir, with DB org_token fallback
- `_update_agent_name_in_config`: traverses all candidate paths
- Agent rename: auto-restarts hxa-connect pm2 to refresh mention filter
- compose up: auto-pulls latest images before starting
- `_normalize_anthropic_api_key`: prevents raw proxy tokens from reaching zylos init

---

## [1.1.0] — 2026-04-01 — HXA Organization + Chat + Admin

### HXA Organization
- Multi-org support with org secrets table
- Bot registration, transfer between orgs, secret rotation
- Admin bot per user per org for DM conversations
- Hub consistency verification in self-check/repair

### Real-time Chat
- DM chat via HXA Connect WebSocket
- Thread (group chat) with participants, invite/kick, announcements
- Message copy button on chat bubbles
- Message search with fulltext index

### Admin Features
- Instance diagnostics: HXA/Telegram/Claude/container status
- Instance control: stop/start/restart/kill_claude
- Resource limits: CPU/memory via docker update
- Default AI model configuration
- Self-check with one-click repair (7-point diagnostics)
- Bot token validation and auto re-registration

### WeChat Integration
- zylos-weixin plugin: QR code login, long-poll messaging, media support
- Marketplace one-click install
- C4 comm-bridge integration

---

## [1.0.0] — 2026-03-31 — Initial Release

### Core Features
- SaaS console for deploying OpenClaw and Zylos AI agent instances
- Docker Compose-based instance lifecycle management
- JWT authentication + PBKDF2-SHA256 password hashing
- MySQL database with auto-migration
- React 19 + Vite 7 + Tailwind CSS frontend
- FastAPI backend with Nginx reverse proxy
- Full English and Chinese i18n
