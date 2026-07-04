import os
import yaml
from dotenv import load_dotenv

load_dotenv("/app/.env", override=False)

CONFIG_PATH = os.environ.get("CONFIG_PATH", "/app/config/settings.yaml")


def load_config() -> dict:
    config = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

    env_overrides = {
        "ollama": {
            "host": os.environ.get("OLLAMA_HOST", "127.0.0.1:11434"),
            "model": os.environ.get("OLLAMA_MODEL", "qwen2:0.5b"),
        },
        "telegram": {
            "bot_token": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            "admin_ids": _parse_admin_ids(os.environ.get("TELEGRAM_ADMIN_IDS", "")),
        },
        "proxy": {
            "base_port": int(os.environ.get("PROXY_BASE_PORT", "10000")),
        },
        "agent": {
            "health_check_interval": int(os.environ.get("HEALTH_CHECK_INTERVAL", "60")),
        },
        "ipv6": {
            "interface": os.environ.get("VPS_IPV6_INTERFACE", "eth0"),
        },
        "security": {
            "auto_firewall": True,
        },
    }

    _deep_merge(config, env_overrides)
    return config


def _parse_admin_ids(ids_str: str) -> list:
    if not ids_str:
        return []
    return [uid.strip() for uid in ids_str.split(",") if uid.strip()]


def _deep_merge(base: dict, override: dict):
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
