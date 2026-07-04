import json
import re

from src.llm.ollama_client import OllamaClient
from src.utils.logger import logger

SYSTEM_PROMPT = """You are an IPv6 proxy management assistant. Parse user requests about proxy management into structured JSON.

CRITICAL: Respond ONLY with valid JSON, no markdown, no extra text. The JSON must follow this exact schema:

{
    "action": "create" | "delete" | "list" | "modify" | "status" | "help",
    "count": number (only for create),
    "protocols": ["vless","vmess","trojan","shadowsocks","socks5","http"],
    "target_id": number or null (for delete/modify),
    "target_ip": string or null (for delete/modify),
    "purpose": string or null (description of intended use)
}

PROTOCOLS available: vless, vmess, trojan, shadowsocks, socks5, http

Examples:
- "create 5 proxies with vless and ss" -> {"action":"create","count":5,"protocols":["vless","shadowsocks"],"target_id":null,"target_ip":null,"purpose":null}
- "how many proxies do I have" -> {"action":"list","count":0,"protocols":[],"target_id":null,"target_ip":null,"purpose":null}
- "delete proxy id 3" -> {"action":"delete","count":0,"protocols":[],"target_id":3,"target_ip":null,"purpose":null}
- "check if proxies are working" -> {"action":"status","count":0,"protocols":[],"target_id":null,"target_ip":null,"purpose":null}
"""


class IntentParser:
    def __init__(self, ollama: OllamaClient):
        self.ollama = ollama

    async def parse(self, user_message: str) -> dict:
        if not user_message or not user_message.strip():
            return {"action": "help", "count": 0, "protocols": [], "target_id": None, "target_ip": None, "purpose": None}

        try:
            response = await self.ollama.generate(
                prompt=f"User request: {user_message}\n\nParse this into JSON:",
                system_prompt=SYSTEM_PROMPT,
                temperature=0.1,
            )
            parsed = self._extract_json(response)
            if parsed:
                return self._normalize(parsed)
        except Exception as e:
            logger.error(f"Intent parsing failed: {e}")

        return self._fallback_parse(user_message)

    def _extract_json(self, text: str) -> dict:
        text = text.strip()

        json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        for pattern in [r'```json\s*(\{.*?\})\s*```', r'```\s*(\{.*?\})\s*```']:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    pass

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        return None

    def _normalize(self, parsed: dict) -> dict:
        result = {
            "action": parsed.get("action", "help"),
            "count": int(parsed.get("count", 0)),
            "protocols": parsed.get("protocols", []),
            "target_id": parsed.get("target_id"),
            "target_ip": parsed.get("target_ip"),
            "purpose": parsed.get("purpose"),
        }

        valid_actions = {"create", "delete", "list", "modify", "status", "help"}
        if result["action"] not in valid_actions:
            result["action"] = "help"

        valid_protocols = {"vless", "vmess", "trojan", "shadowsocks", "socks5", "http"}
        result["protocols"] = [p.lower() for p in result["protocols"] if p.lower() in valid_protocols]
        if not result["protocols"] and result["action"] == "create":
            result["protocols"] = ["vless", "vmess", "trojan", "shadowsocks", "socks5", "http"]

        if result["action"] == "create":
            if result["count"] < 1:
                result["count"] = 1
            if result["count"] > 500:
                result["count"] = 500

        return result

    def _fallback_parse(self, message: str) -> dict:
        msg = message.lower().strip()

        if any(w in msg for w in ["创建", "开", "新建", "create", "add", "新增", "加"]):
            count = 1
            count_match = re.search(r'(\d+)\s*(个|台|条|proxy|代理)', msg)
            if count_match:
                count = int(count_match.group(1))

            protocols = []
            proto_map = {
                "vless": ["vless"],
                "vmess": ["vmess"],
                "trojan": ["trojan"],
                "ss": ["shadowsocks", "ss"],
                "shadowsocks": ["shadowsocks", "ss"],
                "socks5": ["socks5", "socks"],
                "socks": ["socks5", "socks"],
                "http": ["http"],
                "全部": ["vless", "vmess", "trojan", "shadowsocks", "socks5", "http"],
                "所有": ["vless", "vmess", "trojan", "shadowsocks", "socks5", "http"],
            }

            for key, protos in proto_map.items():
                if key in msg:
                    for p in protos:
                        if p not in protocols:
                            protocols.append("shadowsocks" if p == "ss" else p)

            if not protocols:
                protocols = ["vless", "vmess", "trojan", "shadowsocks", "socks5", "http"]

            return {"action": "create", "count": count, "protocols": protocols,
                    "target_id": None, "target_ip": None, "purpose": message}

        if any(w in msg for w in ["删", "删除", "remove", "delete", "del", "移除"]):
            id_match = re.search(r'(\d+)', msg)
            ip_match = re.search(r'([0-9a-f:]{10,})', msg)
            return {"action": "delete", "count": 0, "protocols": [],
                    "target_id": int(id_match.group(1)) if id_match else None,
                    "target_ip": ip_match.group(1) if ip_match else None, "purpose": None}

        if any(w in msg for w in ["检查", "健康", "health", "check"]):
            return {"action": "status", "count": 0, "protocols": [],
                    "target_id": None, "target_ip": None, "purpose": None}

        if any(w in msg for w in ["列", "查", "看", "list", "show", "status", "状态", "统计", "测"]):
            return {"action": "list", "count": 0, "protocols": [],
                    "target_id": None, "target_ip": None, "purpose": None}

        return {"action": "help", "count": 0, "protocols": [],
                "target_id": None, "target_ip": None, "purpose": None}
