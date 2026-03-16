# Deploy Notes

## What remains for `/connect`

Brief inspection of `/home/wwwroot/connect` shows:

- the HXA-Connect server defaults to port `4800`
- the server already supports `BASE_PATH`
- the Next-based web UI already supports `NEXT_PUBLIC_BASE_PATH`

To mount HXA-Connect at `www.ucai.net/connect`, the remaining work is:

1. Build and run the HXA-Connect service from `/home/wwwroot/connect`.
2. Set `BASE_PATH=/connect` for the server process so API and WebSocket URLs resolve under that prefix.
3. Set `NEXT_PUBLIC_BASE_PATH=/connect` when building the Next web UI so client links and WebSocket tickets point to `/connect`.
4. Decide whether `/connect` serves:
   - only the HXA-Connect API/WebSocket server, or
   - the Next UI plus API on the same public prefix
5. Add reverse proxy rules for `/connect` and `/connect/ws` to the running HXA-Connect service.
6. Align auth/session cookie scope with the final public host and prefix.
7. Validate that OpenClaw Hire links or bot setup docs reference the final `/connect` public URL, not localhost paths.

## Public path intent

- `www.ucai.net/openclaw` -> this OpenClaw Hire frontend + backend
- `www.ucai.net/connect` -> existing HXA-Connect deployment from `/home/wwwroot/connect`
