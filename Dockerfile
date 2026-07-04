FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Shanghai \
    LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    OLLAMA_HOST=0.0.0.0:11434 \
    OLLAMA_MODEL=qwen2:0.5b \
    PROXY_BASE_PORT=10000 \
    HEALTH_CHECK_INTERVAL=60 \
    LOG_RETENTION_DAYS=7

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    ca-certificates \
    gnupg \
    lsb-release \
    python3 \
    python3-pip \
    python3-dev \
    iptables \
    iproute2 \
    net-tools \
    iputils-ping \
    procps \
    cron \
    logrotate \
    ndppd \
    vim \
    nano \
    supervisor \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel

ARG XRAY_VERSION=1.8.23
RUN curl -sSL https://github.com/XTLS/Xray-core/releases/download/v${XRAY_VERSION}/Xray-linux-64.zip -o /tmp/xray.zip \
    && mkdir -p /usr/local/share/xray /usr/local/etc/xray /var/log/xray \
    && unzip -q /tmp/xray.zip -d /usr/local/share/xray \
    && mv /usr/local/share/xray/xray /usr/local/bin/xray \
    && chmod +x /usr/local/bin/xray \
    && rm -rf /tmp/xray.zip /usr/local/share/xray/*.dat /usr/local/share/xray/*.json

RUN curl -fsSL https://ollama.com/install.sh | sh

COPY requirements.txt /tmp/requirements.txt
RUN python3 -m pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /app

COPY config/ /app/config/
COPY scripts/ /app/scripts/
COPY src/ /app/src/
COPY entrypoint.sh /app/entrypoint.sh
COPY healthcheck.sh /app/healthcheck.sh

RUN chmod +x /app/entrypoint.sh /app/healthcheck.sh /app/scripts/*.sh

RUN mkdir -p /app/data /app/ollama_data /app/xray_configs /app/certs /var/log/app

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD /app/healthcheck.sh

EXPOSE 10000-65535

ENTRYPOINT ["/app/entrypoint.sh"]
