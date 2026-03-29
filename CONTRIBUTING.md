# Contributing to OpenClaw Hire Console

Thank you for your interest in contributing!

## Development Setup

1. Clone the repo and install dependencies:

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Frontend
cd ../frontend
npm install
```

2. Copy and configure environment:

```bash
cp .env.example .env
# Edit .env with your MySQL credentials and SECRET_KEY
```

3. Start development servers:

```bash
# Backend (auto-reload)
cd backend && uvicorn app.main:app --reload --port 8012

# Frontend (hot-reload)
cd frontend && npm run dev
```

## Code Style

- **Python:** Follow PEP 8. Check with `python3 -m py_compile <file>`.
- **TypeScript:** Check with `npx tsc --noEmit`.
- Keep functions small and reusable.
- Prefer minimal changes that don't affect other modules.

## Pull Requests

1. Create a feature branch from `master`
2. Make your changes with clear commit messages
3. Ensure all compile checks pass
4. Submit a PR with a description of what changed and why

## Reporting Issues

Please include:
- Steps to reproduce
- Expected vs actual behavior
- Environment details (OS, Python/Node version, browser)
