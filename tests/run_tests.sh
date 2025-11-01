#!/bin/bash
# Run TODO service tests

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(cd "$SERVICE_DIR/../../.." && pwd)"

cd "$SERVICE_DIR"

echo "🧪 Running TODO service tests..."

# Install test dependencies if needed
if ! python3 -c "import pytest" 2>/dev/null; then
    echo "Installing pytest and dependencies..."
    pip install pytest pytest-asyncio httpx fastapi || pip3 install pytest pytest-asyncio httpx fastapi
fi

# Run tests
echo "Running database tests..."
python3 -m pytest tests/test_database.py -v --tb=short

echo "Running backup tests..."
python3 -m pytest tests/test_backup.py -v --tb=short

echo "Running API tests..."
python3 -m pytest tests/test_api.py -v --tb=short

echo "Running MCP API tests..."
python3 -m pytest tests/test_mcp_api.py -v --tb=short

echo "✅ All TODO service tests passed!"

