#!/bin/bash
set -e
echo "=== Backend compile check ==="
cd /home/wwwroot/openclaw-hire/backend
.venv/bin/python -m py_compile app/database.py app/schemas.py app/services/install_service.py app/routes/instances.py
echo "Backend OK"

echo "=== Frontend build ==="
cd /home/wwwroot/openclaw-hire/frontend
node_modules/.bin/tsc --noEmit
node_modules/.bin/vite build
echo "Frontend build OK"
