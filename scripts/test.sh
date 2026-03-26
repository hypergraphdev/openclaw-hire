#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Backend Tests ==="
cd "$ROOT_DIR/backend"
python3 -m pytest tests/ -v --tb=short "$@"

echo ""
echo "=== Backend Syntax Check ==="
python3 -m py_compile app/main.py
python3 -m py_compile app/routes/instances.py
python3 -m py_compile app/routes/my_org.py
python3 -m py_compile app/routes/admin.py
python3 -m py_compile app/routes/admin_hxa.py
echo "All Python files OK"

echo ""
echo "=== Frontend Tests ==="
cd "$ROOT_DIR/frontend"
npx vitest run --reporter=verbose
echo ""
echo "=== Frontend Type Check ==="
npx tsc --noEmit
echo "TypeScript OK"
