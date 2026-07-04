#!/bin/bash
set -e

INTERFACE="${VPS_IPV6_INTERFACE:-eth0}"

echo "[setup_ndp] Checking NDP Proxy requirement..."

GATEWAY_IPV6=$(ip -6 route show default 2>/dev/null | awk '{print $3}' | head -1)
if [ -z "${GATEWAY_IPV6}" ]; then
    echo "[setup_ndp] No IPv6 default gateway found, checking routes..."
    GATEWAY_IPV6=$(ip -6 route show default 2>/dev/null | grep -oP 'via \K[0-9a-f:]+' | head -1)
fi

if [ -z "${GATEWAY_IPV6}" ]; then
    echo "[setup_ndp] WARNING: Could not determine IPv6 gateway. NDP Proxy may not be needed."
    echo "NDP_PROXY_REQUIRED=false" >> /app/data/ipv6_env
    exit 0
fi

echo "[setup_ndp] IPv6 gateway: ${GATEWAY_IPV6}"

TEST_ADDR="${IPV6_SUBNET}::ffff"
ip -6 addr add "${TEST_ADDR}/128" dev "${INTERFACE}" 2>/dev/null || true

ping6 -c 1 -W 2 "${GATEWAY_IPV6}" -I "${INTERFACE}" 2>/dev/null && NDP_NEEDED=false || NDP_NEEDED=true

ip -6 addr del "${TEST_ADDR}/128" dev "${INTERFACE}" 2>/dev/null || true

if [ "${NDP_NEEDED}" = "true" ]; then
    echo "[setup_ndp] NDP Proxy required. Configuring ndppd..."

    cat > /etc/ndppd.conf << NDPEOL
route-ttl 30000
address-ttl 30000

proxy ${INTERFACE} {
    router yes
    timeout 500
    ttl 30000

    rule ${IPV6_SUBNET}::/${IPV6_PREFIX} {
        static
    }
}
NDPEOL

    kill $(pgrep ndppd 2>/dev/null) 2>/dev/null || true
    sleep 1
    ndppd -d 2>&1 | tee /var/log/ndppd.log &
    sleep 1

    if pgrep ndppd > /dev/null 2>&1; then
        echo "[setup_ndp] ndppd started successfully."
        echo "NDP_PROXY_REQUIRED=true" >> /app/data/ipv6_env
    else
        echo "[setup_ndp] WARNING: ndppd failed to start."
        echo "NDP_PROXY_REQUIRED=false" >> /app/data/ipv6_env
    fi
else
    echo "[setup_ndp] NDP Proxy not required. Direct routing works."
    echo "NDP_PROXY_REQUIRED=false" >> /app/data/ipv6_env
fi
