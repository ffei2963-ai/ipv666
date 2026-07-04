#!/bin/bash

OLLAMA_PID=$(pgrep -f "ollama serve" 2>/dev/null || true)
XRAY_PID=$(pgrep -f "xray run" 2>/dev/null || true)
APP_PID=$(pgrep -f "python3 /app/src/main.py" 2>/dev/null || true)

if [ -z "$OLLAMA_PID" ]; then
    echo "[healthcheck] Ollama not running"
    exit 1
fi

if [ -z "$XRAY_PID" ]; then
    echo "[healthcheck] Xray not running"
    exit 1
fi

if [ -z "$APP_PID" ]; then
    echo "[healthcheck] Main app not running"
    exit 1
fi

OLLAMA_HEALTH=$(curl -sf http://127.0.0.1:11434/api/tags 2>/dev/null || true)
if [ -z "$OLLAMA_HEALTH" ]; then
    echo "[healthcheck] Ollama API not reachable"
    exit 1
fi

echo "[healthcheck] All services healthy"
exit 0
