#!/bin/bash
set -e

echo "[setup_ollama] Starting Ollama service..."

OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:11434}"

if pgrep -f "ollama serve" > /dev/null 2>&1; then
    echo "[setup_ollama] Ollama already running."
else
    OLLAMA_HOST="${OLLAMA_HOST}" nohup ollama serve > /var/log/ollama.log 2>&1 &
    echo "[setup_ollama] Waiting for Ollama to start..."
    for i in $(seq 1 30); do
        if curl -sf http://127.0.0.1:11434/api/tags > /dev/null 2>&1; then
            echo "[setup_ollama] Ollama started successfully."
            break
        fi
        if [ $i -eq 30 ]; then
            echo "[setup_ollama] ERROR: Ollama failed to start within 30s."
            cat /var/log/ollama.log 2>/dev/null || true
            exit 1
        fi
        sleep 1
    done
fi

MODEL="${OLLAMA_MODEL:-qwen2:0.5b}"

echo "[setup_ollama] Checking model: ${MODEL}..."

if curl -sf http://127.0.0.1:11434/api/tags | grep -q "\"name\":\"${MODEL}\""; then
    echo "[setup_ollama] Model '${MODEL}' already exists."
else
    echo "[setup_ollama] Pulling model '${MODEL}'... This may take a few minutes."
    ollama pull "${MODEL}" 2>&1 | tee /var/log/ollama_pull.log

    if curl -sf http://127.0.0.1:11434/api/tags | grep -q "\"name\":\"${MODEL}\""; then
        echo "[setup_ollama] Model '${MODEL}' pulled successfully."
    else
        echo "[setup_ollama] ERROR: Failed to pull model '${MODEL}'."
        exit 1
    fi
fi

echo "[setup_ollama] Testing model..."
ollama run "${MODEL}" "Hello, respond with OK only." 2>/dev/null | grep -qi "ok\|OK" && \
    echo "[setup_ollama] Model test passed." || \
    echo "[setup_ollama] WARNING: Model test returned unexpected result."

echo "[setup_ollama] Ollama setup completed."
