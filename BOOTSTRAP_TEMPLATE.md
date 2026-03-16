# OpenClaw Hire Bootstrap Template

This repository only ships the hiring control plane scaffold. It does not pretend that employee runtime provisioning is complete.

## Intended bootstrap path

Use the existing "security-auditor style" setup as the source pattern for each hired employee workspace:

1. Start from the audited template repository or local seed used for the security-auditor agent.
2. Clone or copy that seed into a per-employee workspace directory.
3. Rewrite agent metadata:
   - employee name
   - role / brief
   - owner identifier
   - default model `openai-codex/gpt-5.3-codex-spark`
4. Write environment placeholders only:
   - Telegram bot token placeholder
   - HXA-Connect org or bot credentials if needed later
   - deployment hostname / path assumptions
5. Draft service files and reverse proxy snippets, but keep them disabled until secrets are supplied and reviewed.
6. Mark the employee record as `waiting_bot_token`.
7. Only after the token exists should provisioning continue to:
   - enable service units
   - register webhook / bot connectivity
   - move the employee to `ready`

## Non-goals in this first scaffold

- No fake service creation
- No fake git clone execution
- No fake Telegram bot registration
- No fake HXA-Connect enrollment

## Suggested future automation

- Add a worker that consumes queued employee jobs
- Store bootstrap template source path in config
- Add explicit failure transitions with operator notes
- Generate per-employee workspace manifests for auditability
