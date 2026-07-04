#!/bin/bash
set -e

echo "[setup_xray] Initializing Xray-core configuration..."

XRAY_CONFIG_DIR="/usr/local/etc/xray"
XRAY_CONFIG="${XRAY_CONFIG_DIR}/config.json"
XRAY_LOG_DIR="/var/log/xray"

mkdir -p "${XRAY_CONFIG_DIR}" "${XRAY_LOG_DIR}"

if [ ! -f "${XRAY_CONFIG}" ]; then
    cat > "${XRAY_CONFIG}" << 'XRAYEOF'
{
  "log": {
    "loglevel": "warning",
    "access": "/var/log/xray/access.log",
    "error": "/var/log/xray/error.log"
  },
  "inbounds": [],
  "outbounds": [
    {
      "protocol": "freedom",
      "settings": {},
      "tag": "direct"
    },
    {
      "protocol": "blackhole",
      "settings": {},
      "tag": "blocked"
    }
  ],
  "routing": {
    "domainStrategy": "IPIfNonMatch",
    "rules": [
      {
        "type": "field",
        "ip": ["geoip:private"],
        "outboundTag": "blocked"
      }
    ]
  }
}
XRAYEOF
    echo "[setup_xray] Default Xray config created."
fi

if pgrep xray > /dev/null 2>&1; then
    echo "[setup_xray] Xray already running. Skipping start."
else
    echo "[setup_xray] Starting Xray-core..."
    nohup xray run -config "${XRAY_CONFIG}" > /var/log/xray/xray.log 2>&1 &
    sleep 2
    if pgrep xray > /dev/null 2>&1; then
        echo "[setup_xray] Xray-core started successfully."
    else
        echo "[setup_xray] ERROR: Xray-core failed to start."
        cat /var/log/xray/xray.log 2>/dev/null || true
        exit 1
    fi
fi

cat > /etc/logrotate.d/xray << EOF
/var/log/xray/*.log {
    daily
    rotate ${LOG_RETENTION_DAYS:-7}
    missingok
    notifempty
    compress
    delaycompress
    copytruncate
}
EOF

echo "[setup_xray] Xray setup completed."
