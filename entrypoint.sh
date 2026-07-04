#!/bin/bash
set -e

echo "============================================"
echo "  IPv666 - IPv6 Proxy Station Group Server"
echo "  Starting up..."
echo "============================================"

export PYTHONPATH=/app
export OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2:0.5b}"

/app/scripts/setup_ipv6.sh
/app/scripts/setup_ndp.sh
/app/scripts/setup_tls.sh
/app/scripts/setup_xray.sh
/app/scripts/setup_ollama.sh
/app/scripts/setup_firewall.sh

echo "[entrypoint] All setup scripts completed."
echo "[entrypoint] Starting main application..."
exec python3 /app/src/main.py
