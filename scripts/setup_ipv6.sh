#!/bin/bash
set -e

INTERFACE="${VPS_IPV6_INTERFACE:-eth0}"

echo "[setup_ipv6] Detecting IPv6 subnet on interface: ${INTERFACE}"

IPV6_ADDR=$(ip -6 addr show dev "${INTERFACE}" scope global 2>/dev/null | grep -oP 'inet6 \K[0-9a-f:]+' | head -1)
if [ -z "${IPV6_ADDR}" ]; then
    echo "[setup_ipv6] ERROR: No global IPv6 address found on ${INTERFACE}"
    exit 1
fi

IPV6_PREFIX=$(ip -6 addr show dev "${INTERFACE}" scope global 2>/dev/null | grep -oP 'inet6 \K[0-9a-f:/]+' | grep -oP '/\d+' | head -1 | tr -d '/')
if [ -z "${IPV6_PREFIX}" ]; then
    IPV6_PREFIX="64"
fi

IPV6_SUBNET=$(echo "${IPV6_ADDR}" | sed -E 's/([0-9a-f:]+):[0-9a-f]+$/\1/')

echo "[setup_ipv6] Primary IPv6: ${IPV6_ADDR}"
echo "[setup_ipv6] Subnet prefix: /${IPV6_PREFIX}"
echo "[setup_ipv6] Subnet base:  ${IPV6_SUBNET}::"

echo "IPV6_INTERFACE=${INTERFACE}" > /app/data/ipv6_env
echo "IPV6_ADDR=${IPV6_ADDR}" >> /app/data/ipv6_env
echo "IPV6_PREFIX=${IPV6_PREFIX}" >> /app/data/ipv6_env
echo "IPV6_SUBNET=${IPV6_SUBNET}" >> /app/data/ipv6_env

SYSCTL_CONF="/etc/sysctl.d/99-ipv666.conf"
cat > "${SYSCTL_CONF}" << EOF
net.ipv6.conf.all.forwarding = 1
net.ipv6.conf.${INTERFACE}.forwarding = 1
net.ipv6.conf.${INTERFACE}.accept_ra = 1
net.ipv6.conf.${INTERFACE}.proxy_ndp = 1
net.ipv6.conf.${INTERFACE}.accept_dad = 1
net.ipv6.neigh.${INTERFACE}.gc_stale_time = 60
EOF

sysctl -p "${SYSCTL_CONF}" 2>/dev/null || true

if [ -f /app/data/ipv6_persist ]; then
    echo "[setup_ipv6] Restoring previously allocated IPv6 addresses..."
    while IFS= read -r addr; do
        [ -z "$addr" ] && continue
        if ! ip -6 addr show dev "${INTERFACE}" | grep -qF "${addr}"; then
            ip -6 addr add "${addr}/${IPV6_PREFIX}" dev "${INTERFACE}" 2>/dev/null || true
            echo "[setup_ipv6] Restored: ${addr}"
        fi
    done < /app/data/ipv6_persist
fi

echo "[setup_ipv6] IPv6 setup completed."
