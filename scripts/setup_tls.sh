#!/bin/bash
set -e

echo "[setup_tls] Checking TLS configuration..."

TLS_ENABLED="${TLS_ENABLED:-false}"
TLS_DOMAIN="${TLS_DOMAIN:-}"
TLS_EMAIL="${TLS_EMAIL:-admin@example.com}"

if [ "${TLS_ENABLED}" != "true" ] || [ -z "${TLS_DOMAIN}" ]; then
    echo "[setup_tls] TLS is disabled or no domain configured. Generating self-signed cert as fallback..."

    if [ ! -f /app/certs/cert.pem ]; then
        openssl req -x509 -newkey rsa:2048 -keyout /app/certs/key.pem \
            -out /app/certs/cert.pem -days 3650 -nodes \
            -subj "/C=US/ST=State/L=City/O=IPv666/CN=localhost" 2>/dev/null
        echo "[setup_tls] Self-signed certificate generated."
    fi
    exit 0
fi

echo "[setup_tls] TLS enabled for domain: ${TLS_DOMAIN}"

if ! command -v acme.sh &> /dev/null; then
    echo "[setup_tls] Installing acme.sh..."
    curl -sSL https://get.acme.sh | sh -s email="${TLS_EMAIL}"
    source /root/.acme.sh/acme.sh.env 2>/dev/null || true
    ACME_BIN="/root/.acme.sh/acme.sh"
else
    ACME_BIN=$(command -v acme.sh)
fi

CERT_DIR="/app/certs/${TLS_DOMAIN}"
mkdir -p "${CERT_DIR}"

if [ -f "${CERT_DIR}/fullchain.cer" ] && [ -f "${CERT_DIR}/${TLS_DOMAIN}.key" ]; then
    echo "[setup_tls] Certificate already exists. Checking expiry..."
    EXPIRY=$(openssl x509 -enddate -noout -in "${CERT_DIR}/fullchain.cer" 2>/dev/null | cut -d= -f2)
    echo "[setup_tls] Certificate expires: ${EXPIRY}"
else
    echo "[setup_tls] Issuing certificate for ${TLS_DOMAIN}..."

    "${ACME_BIN}" --issue -d "${TLS_DOMAIN}" --standalone \
        --key-file "${CERT_DIR}/${TLS_DOMAIN}.key" \
        --fullchain-file "${CERT_DIR}/fullchain.cer" \
        --force 2>&1 || {
        echo "[setup_tls] WARNING: acme.sh failed. Using self-signed fallback."
        openssl req -x509 -newkey rsa:2048 -keyout /app/certs/key.pem \
            -out /app/certs/cert.pem -days 365 -nodes \
            -subj "/CN=${TLS_DOMAIN}" 2>/dev/null
    }
fi

if [ -f "${CERT_DIR}/fullchain.cer" ]; then
    cp "${CERT_DIR}/fullchain.cer" /app/certs/cert.pem
    cp "${CERT_DIR}/${TLS_DOMAIN}.key" /app/certs/key.pem
    echo "[setup_tls] TLS certificates ready."
else
    echo "[setup_tls] WARNING: No valid certificate obtained."
fi
