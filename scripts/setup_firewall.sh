#!/bin/bash
set -e

echo "[setup_firewall] Configuring firewall rules..."

FIREWALL_TYPE="${FIREWALL_TYPE:-iptables}"

if [ "${AUTO_FIREWALL:-true}" != "true" ]; then
    echo "[setup_firewall] Auto firewall is disabled."
    exit 0
fi

INTERFACE="${VPS_IPV6_INTERFACE:-eth0}"
BASE_PORT="${PROXY_BASE_PORT:-10000}"
MAX_PORT=$((BASE_PORT + 50000))

if [ "${FIREWALL_TYPE}" = "nftables" ] && command -v nft &> /dev/null; then
    echo "[setup_firewall] Using nftables..."
    nft add table inet ipv666 2>/dev/null || true
    nft add chain inet ipv666 input { type filter hook input priority 0\; } 2>/dev/null || true

    nft list chain inet ipv666 input 2>/dev/null | grep -q "ipv666-proxy" || \
        nft add rule inet ipv666 input tcp dport ${BASE_PORT}-${MAX_PORT} accept comment \"ipv666-proxy\"

    nft list chain inet ipv666 input 2>/dev/null | grep -q "ipv666-established" || \
        nft add rule inet ipv666 input ct state established,related accept comment \"ipv666-established\"
    echo "[setup_firewall] nftables rules added."
elif command -v iptables &> /dev/null; then
    echo "[setup_firewall] Using iptables..."

    iptables -C INPUT -p tcp --dport ${BASE_PORT}:${MAX_PORT} -j ACCEPT 2>/dev/null || \
        iptables -A INPUT -p tcp --dport ${BASE_PORT}:${MAX_PORT} -j ACCEPT

    ip6tables -C INPUT -p tcp --dport ${BASE_PORT}:${MAX_PORT} -j ACCEPT 2>/dev/null || \
        ip6tables -A INPUT -p tcp --dport ${BASE_PORT}:${MAX_PORT} -j ACCEPT

    iptables -C INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || \
        iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

    ip6tables -C INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || \
        ip6tables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

    ip6tables -C INPUT -i lo -j ACCEPT 2>/dev/null || \
        ip6tables -A INPUT -i lo -j ACCEPT

    echo "[setup_firewall] iptables rules added."
else
    echo "[setup_firewall] WARNING: No firewall tool found."
fi

echo "[setup_firewall] Firewall setup completed."
