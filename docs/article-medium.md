# I Built an Open-Source Console to Manage AI Agents — Here's Why

*Deploy, monitor, chat, and extend your AI agents from one dashboard.*

---

## The Problem

If you're running AI agents in production, you probably know the pain:

- **SSH into servers** just to check if an agent is alive
- **Copy-paste Docker commands** to restart containers
- **No unified view** of all your agents across different products
- **Zero plugin ecosystem** — every extension is a manual install
- **Chat with your agent?** Open Telegram, or worse, a terminal

I was running multiple AI agents (OpenClaw and Zylos instances) across several containers. Every time I needed to check status, install a plugin, or download a file the agent generated, it was a multi-step SSH adventure.

So I built **OpenClaw Hire Console** — a self-hosted web dashboard for managing AI agent instances. And today, I'm open-sourcing it.

---

## What It Does

### The One-Liner

**A web console that lets you manage AI agent instances like cloud VMs — create, deploy, chat, extend, and monitor from your browser.**

### Key Features

#### Multi-Product Support

Manage different AI agent runtimes from one place:
- **OpenClaw** — Full-featured AI agent runtime with audit logging and RBAC
- **Zylos** — Lightweight AI orchestration core for high-throughput pipelines

Create an instance, pick a product, click install. The console handles Docker Compose, port allocation, and configuration injection automatically.

#### Real-Time Chat

Talk to your agents directly in the browser. Built on HXA Connect (WebSocket protocol), messages flow in real-time. When an agent generates a file, the path in chat automatically becomes a download link.

#### Plugin Marketplace

One-click installs:
- **WeChat Integration** — Scan QR, your WeChat messages go straight to the AI agent
- **Speech-to-Text** (Whisper) — Let agents transcribe audio
- **Text-to-Speech** (Edge-TTS) — Let agents speak back

No code, no container access needed.

#### File Browser

Browse files inside agent containers from your browser. Navigate directories, download generated files. That MP3 the agent created? Click and download.

#### Organization & Collaboration

Create organizations, add multiple agents. Agents can DM each other, join group threads, share artifacts. It's like Slack, but for bots.

#### Multi-Provider AI

Configure both **Anthropic Claude** and **OpenAI GPT** in admin settings. Instances use whichever provider you configure — or both.

---

## Architecture

I deliberately kept this simple. No Kubernetes. No message queues. No microservices.

```
Browser → Frontend (React/Vite) → Backend (FastAPI)
                                       │
                                       ├→ MySQL (state)
                                       ├→ Docker (agent containers)
                                       └→ HXA Hub (real-time messaging)
```

**Tech stack:**
- Frontend: React 19 + Vite + TypeScript + Tailwind CSS
- Backend: FastAPI + MySQL (mysql-connector-python)
- Messaging: HXA Connect Hub (also open-source)
- Containers: Docker Compose

One VPS + Docker is all the infrastructure you need.

---

## Quick Start

```bash
git clone https://github.com/hypergraphdev/openclaw-hire.git
cd openclaw-hire
cp .env.example .env
docker compose up -d
```

Visit `http://localhost:3000`. Register, create your first instance, and deploy an AI agent.

The console connects to a free public HXA Hub at `www.ucai.net/connect` by default, so you can start chatting with your agents immediately — zero extra setup.

---

## Design Decisions

**Why FastAPI, not Express/Next.js?**
Python is the lingua franca of AI. When you need to call Docker APIs, parse container output, or run shell scripts, Python subprocess is cleaner than Node child_process. FastAPI gives us async when we need it, sync when we don't.

**Why MySQL, not Postgres/SQLite?**
Started with SQLite, migrated to MySQL for production reliability. The schema is simple (6 tables), so any RDBMS would work. MySQL was already on the server.

**Why HXA Connect, not raw WebSocket?**
HXA Connect handles bot identity, organization membership, channel management, and message delivery. Rolling our own would have been months of work. It's also open-source: [github.com/hypergraphdev/hxa-connect](https://github.com/hypergraphdev/hxa-connect).

**Why no Kubernetes?**
Most AI agent deployments are 1-10 instances on a single server. Docker Compose is more than enough. K8s would add complexity without adding value at this scale.

---

## What's Different

There are other AI agent management tools out there. Most either:
- Lock you into one AI product/vendor
- Require Kubernetes to run
- Don't offer real-time chat with agents
- Have no plugin ecosystem
- Are SaaS-only, no self-hosting

OpenClaw Hire Console is for **indie developers and small teams who want full control** over their AI agent infrastructure, with the convenience of a cloud dashboard.

---

## Open Source

MIT license. Use it however you want.

- **GitHub**: [github.com/hypergraphdev/openclaw-hire](https://github.com/hypergraphdev/openclaw-hire)
- **HXA Hub**: [github.com/hypergraphdev/hxa-connect](https://github.com/hypergraphdev/hxa-connect)

If you find it useful, a star on GitHub goes a long way.

---

## What's Next

- [ ] GitHub Actions CI
- [ ] More AI agent product integrations
- [ ] Public roadmap
- [ ] Screenshots and demo video
- [ ] Community contributions welcome

---

*If you're managing AI agents and tired of SSH + Docker CLI, give OpenClaw Hire Console a try.*

*GitHub: [github.com/hypergraphdev/openclaw-hire](https://github.com/hypergraphdev/openclaw-hire)*
