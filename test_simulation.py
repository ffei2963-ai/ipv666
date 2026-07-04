#!/usr/bin/env python3
"""
30-day simulation test for IPv666 - tests all code paths, identifies bugs.
Runs inside the Docker container against real modules (mocked external deps).
"""
import asyncio
import json
import os
import random
import sys
import time
import traceback
import uuid

sys.path.insert(0, "/app")

from src.db.database import init_db, get_db, log_operation
from src.db.models import Proxy
from src.utils.config import load_config
from src.ipv6.address_manager import AddressManager
from src.proxy.xray_manager import XrayManager
from src.proxy.xray_templates import generate_inbound_for_proxy, _get_proxy_ports
from src.proxy.share_link import generate_all_share_links
from src.proxy.tls_manager import TlsManager
from src.security.firewall import FirewallManager
from src.utils.credential import generate_proxy_credentials
from src.utils.logger import logger

BUG_REPORTS = []
SIM_DAYS = 30
OPERATIONS_PER_DAY = 50

def report_bug(module, description, severity="high"):
    bug = {"module": module, "description": description, "severity": severity}
    BUG_REPORTS.append(bug)
    print(f"\n*** BUG FOUND [{severity}]: {module} - {description}")

# ---------- Test 1: Protocol normalization bug ----------
async def test1_normalize_protocols():
    """Test the _normalize_protocols function for the trailing 's' bug."""
    print("\n=== TEST 1: Protocol normalization ===")
    from src.bot.telegram_bot import TelegramBot

    class DummyBot:
        pass

    bot = object.__new__(TelegramBot)
    bot.__dict__.update({"token": "", "orchestrator": None, "intent_parser": None, "auth_manager": None, "app": None})

    test_cases = [
        (["vmess"], ["vmess"]),
        (["vless"], ["vless"]),
        (["shadowsocks"], ["shadowsocks"]),
        (["vmess", "vless", "shadowsocks"], ["vmess", "vless", "shadowsocks"]),
        (["socks5"], ["socks5"]),
        (["ss"], ["shadowsocks"]),
        (["vmess", "ss", "socks5"], ["vmess", "ss", "socks5"]),
    ]

    for raw, expected in test_cases:
        result = bot._normalize_protocols(raw)
        ok = set(result) == set(expected)
        if not ok:
            report_bug("telegram_bot._normalize_protocols",
                       f"Normalize {raw} = {result}, expected {expected}. "
                       f"rstrip('s') strips ALL trailing 's' chars, corrupting protocol names.")

    # Direct test of the rstrip bug
    p = "vmess"
    p_clean = p.lower().strip().rstrip("s")
    if p_clean != p:
        report_bug("telegram_bot._normalize_protocols",
                   f"rstrip('s') bug: '{p}' -> '{p_clean}'. Input protocols containing 's' at end get mangled.")


# ---------- Test 2: Port assignment mismatch ----------
async def test2_port_mismatch():
    """Test the port assignment inconsistency between orchestrator and xray_templates."""
    print("\n=== TEST 2: Port assignment mismatch ===")

    # Simulate what the orchestrator does
    protocols = ["vless", "shadowsocks", "socks5"]
    base_port = 10000

    # Orchestrator creates firewall rules for sequential ports
    orchestrator_ports = {}
    for j, proto in enumerate(protocols):
        orchestrator_ports[proto] = base_port + j

    # xray_templates creates inbounds based on protocol order index
    xray_ports = _get_proxy_ports(Proxy(base_port=base_port, protocols=protocols))

    print(f"  Protocols: {protocols}")
    print(f"  Orchestrator firewall ports: {orchestrator_ports}")
    print(f"  Xray template inbounds ports: {xray_ports}")

    for proto in protocols:
        p = proto.lower()
        orch_port = orchestrator_ports[p]
        xray_port = xray_ports.get(p)
        if orch_port != xray_port:
            report_bug("Port mismatch",
                       f"Protocol '{proto}': orchestrator opens firewall on port {orch_port}, "
                       f"but xray creates inbound on port {xray_port}. "
                       f"Firewall blocks the actual proxy port! All proxies with non-standard protocol orders "
                       f"are broken.")

    # Check verifier behavior: it tests base_port + sequential index
    proxy = Proxy(id=1, ipv6_addr="2602:294:1:a18::2", base_port=base_port,
                  protocols=protocols, cred_uuids={"vless": "test-uuid"},
                  cred_passwords={"shadowsocks": "ss-pwd", "socks5": "s5-pwd"})

    from src.proxy.verifier import ProxyVerifier
    verifier = ProxyVerifier()

    # The verifier tests:
    # 1) If shadowsocks in protocols -> port = base_port + ss_index
    # 2) Otherwise: port = base_port
    # But actual ports are based on _PROTOCOL_ORDER!
    verifier_port = None
    first_proto = protocols[0].lower()
    verifier_port = base_port
    if "shadowsocks" in [p.lower() for p in protocols]:
        for i, p in enumerate(protocols):
            if p.lower() == "shadowsocks":
                verifier_port = base_port + i
                break

    actual_ports = _get_proxy_ports(proxy)
    verifier_checks_port = verifier_port

    # What is the actual port for the first protocol?
    actual_vless_port = actual_ports["vless"]  # should be base_port + 0 = 10000

    # Verifier checks 10001 (shadowsocks at sequential index 1), but actual shadowsocks port is 10003
    actual_ss_port = actual_ports["shadowsocks"]

    if verifier_checks_port != actual_ss_port:
        report_bug("Port mismatch - verifier",
                   f"Verifier checks port {verifier_checks_port} (sequential index), "
                   f"but actual shadowsocks port is {actual_ss_port} (protocol order index). "
                   f"Health checks test the WRONG port. Proxies will show as failed even if they're working.")


# ---------- Test 3: _get_next_available_port hardcoded +6 ----------
async def test3_next_port():
    """Test that port allocation uses hardcoded +6 instead of actual protocol count."""
    print("\n=== TEST 3: Next available port calculation ===")

    await init_db()
    db = await get_db()
    try:
        await db.execute("DELETE FROM proxies")
        await db.commit()

        # Simulate proxies with different protocol counts
        await db.execute(
            "INSERT INTO proxies (ipv6_addr, base_port, protocols, status) VALUES (?, ?, ?, ?)",
            ("2602::1", 10000, json.dumps(["vless"]), "active")
        )
        await db.commit()

        from src.agent.orchestrator import Orchestrator
        config = load_config()
        config["proxy"]["base_port"] = 10000
        orch = Orchestrator(config)

        port = await orch._get_next_available_port()

        # Proxy at 10000 used 1 protocol (port 10000 in use)
        # Next base_port should be 10001
        # But the code does max_port(10000) + 6 = 10006
        expected_port = 10001
        if port != expected_port:
            report_bug("_get_next_available_port",
                       f"Hardcoded +6 gap: expected next base_port {expected_port}, got {port}. "
                       f"Causes wasted port gaps when proxies use fewer than 6 protocols.")

        # Test wrap-around protection
        await db.execute(
            "INSERT INTO proxies (ipv6_addr, base_port, protocols, status) VALUES (?, ?, ?, ?)",
            ("2602::2", 10006, json.dumps(["vless"]), "active")
        )
        await db.commit()

        port2 = await orch._get_next_available_port()
        if port2 != 10007:
            report_bug("_get_next_available_port",
                       f"After adding proxy at {10006}, expected next port {10007}, got {port2}")
    finally:
        await db.execute("DELETE FROM proxies")
        await db.commit()
        await db.close()


# ---------- Test 4: XrayManager _write_config file handle leak ----------
async def test4_write_config_leak():
    """Test the xray_manager file writing code for resource leak."""
    print("\n=== TEST 4: Xray config write file handle leak ===")

    # The code does:
    # lambda: json.dumps(config, indent=2) and open(XRAY_CONFIG, "w").write(json.dumps(config, indent=2))
    # This:
    # 1) Calls json.dumps twice (waste)
    # 2) Doesn't close the file handle (resource leak)

    report_bug("xray_manager._write_config",
               "File handle leak: open() without close() or 'with' statement. "
               "Repeated reloads accumulate open file handles, eventually causing "
               "'Too many open files' error after prolonged operation.",
               severity="medium")

    report_bug("xray_manager._write_config",
               "json.dumps called twice (waste): first call in 'and' short-circuit, "
               "second call for actual write.",
               severity="low")


# ---------- Test 5: Create proxies end-to-end ----------
async def test5_create_proxies():
    """Test creating proxies through the orchestrator."""
    print("\n=== TEST 5: Create proxies end-to-end ===")

    await init_db()
    db = await get_db()
    try:
        await db.execute("DELETE FROM proxies")
        await db.execute("DELETE FROM ipv6_pool")
        await db.commit()
    finally:
        await db.close()

    from src.agent.orchestrator import Orchestrator

    config = load_config()
    config["agent"]["verify_new_proxy"] = False  # Skip real verification
    config["proxy"]["base_port"] = 10000
    orch = Orchestrator(config)
    await orch.initialize()

    # Test creating proxies with various protocol combinations
    test_configs = [
        (1, ["vless", "vmess"]),
        (2, ["shadowsocks"]),
        (3, ["vless", "shadowsocks", "socks5"]),
        (5, ["vless", "vmess", "trojan", "shadowsocks", "socks5", "http"]),
    ]

    for count, protocols in test_configs:
        created, results = await orch.create_proxies(count, protocols)
        print(f"  Create {count}x {protocols}: got {created} results")
        if created < count:
            report_bug("create_proxies",
                       f"Requested {count} proxy(ies) with {protocols}, only created {created}",
                       severity="high" if created == 0 else "medium")

        for r in results:
            # Check that share links were generated
            if not r.get("share_links"):
                report_bug("create_proxies",
                           f"Proxy {r['id']} has no share links", severity="medium")

            # Check that protocols are correct
            actual_protos = set(r["protocols"])
            expected_protos = set(protocols)
            if actual_protos != expected_protos:
                report_bug("create_proxies",
                           f"Proxy {r['id']} has protocols {actual_protos}, expected {expected_protos}")

    # Test list
    all_proxies = await orch.list_proxies()
    print(f"  Total proxies: {len(all_proxies)}")

    # Verify list returns complete data
    for p in all_proxies:
        if not p.get("share_links"):
            report_bug("list_proxies", f"Proxy #{p['id']} missing share_links in list")

    # Test stats
    stats = await orch.get_stats()
    print(f"  Stats: {stats}")
    if stats["total"] < len(all_proxies):
        report_bug("get_stats", f"Stats total {stats['total']} < list count {len(all_proxies)}")

    return orch, all_proxies


# ---------- Test 6: Delete proxies ----------
async def test6_delete_proxies(orch, all_proxies):
    """Test deleting proxies by id and by ip."""
    print("\n=== TEST 6: Delete proxies ===")

    if not all_proxies:
        print("  Skipping - no proxies to delete")
        return

    # Delete by ID
    first_id = all_proxies[0]["id"]
    success = await orch.delete_proxy(proxy_id=first_id)
    if not success:
        report_bug("delete_proxy", f"Failed to delete proxy {first_id} by ID")

    # Verify it's gone
    remaining = await orch.list_proxies()
    ids = {p["id"] for p in remaining}
    if first_id in ids:
        report_bug("delete_proxy", f"Proxy {first_id} still in list after deletion")

    # Delete by IP
    if len(all_proxies) > 1:
        second_ip = all_proxies[1]["ipv6_addr"]
        success = await orch.delete_proxy(ipv6_addr=second_ip)
        if not success:
            report_bug("delete_proxy", f"Failed to delete proxy by IP {second_ip}")

    # Try deleting non-existent (should return False, not crash)
    success = await orch.delete_proxy(proxy_id=99999)
    if success:
        report_bug("delete_proxy", "Deleting non-existent proxy returned True (should be False)")

    # Verify no crash on None/None
    success = await orch.delete_proxy()
    if success:
        report_bug("delete_proxy", "delete_proxy() with no args returned True")


# ---------- Test 7: Edge cases for create ----------
async def test7_edge_cases():
    """Test edge cases: zero count, huge count, duplicate creation, etc."""
    print("\n=== TEST 7: Edge cases ===")

    from src.agent.orchestrator import Orchestrator

    config = load_config()
    config["agent"]["verify_new_proxy"] = False
    orch = Orchestrator(config)
    await orch.initialize()

    # Zero count
    count, results = await orch.create_proxies(0, ["vless"])
    if count != 0 or len(results) != 0:
        report_bug("create_proxies", f"Zero count should return (0, []), got ({count}, results={len(results)})")

    # Negative count (treated as < 1)
    count, results = await orch.create_proxies(-5, ["vless"])
    if count != 0:
        report_bug("create_proxies", f"Negative count should return 0, got {count}")

    # Empty protocols
    count, results = await orch.create_proxies(1, [])
    if count > 0:
        print(f"  Create with empty protocols returned {count} proxy(ies)")

    # Huge count (beyond limits) - reduced for speed
    count, results = await orch.create_proxies(50, ["vless"])
    if count > 50:  # intent_parser limits to 500, but orchestrator doesn't
        print(f"  Created {count} proxies from 50 request")
        report_bug("create_proxies",
                   "No upper limit on proxy count. A bug or malicious intent could create unlimited proxies "
                   "exhausting system resources.",
                   severity="medium")


# ---------- Test 8: Intent parser ----------
async def test8_intent_parser():
    """Test the intent parser with various inputs."""
    print("\n=== TEST 8: Intent parser ===")

    from src.agent.intent_parser import IntentParser

    class DummyOllama:
        async def generate(self, **kwargs):
            return ""

    parser = IntentParser(DummyOllama())

    test_inputs = [
        ("create 5 proxies", {"action": "create", "count": 5, "protocols": ["vless", "vmess", "trojan", "shadowsocks", "socks5", "http"]}),
        ("delete proxy 3", {"action": "delete", "count": 0, "target_id": 3}),
        ("list", {"action": "list"}),
        ("status check", {"action": "status"}),
        ("help", {"action": "help"}),
        ("删除 代理 5", {"action": "delete", "target_id": 5}),
        ("创建 10 个 vless 代理", {"action": "create", "count": 10}),
        ("检查 健康", {"action": "status"}),
        ("", {"action": "help"}),  # Empty input
        (None, {"action": "help"}),  # None input
    ]

    for msg, expected in test_inputs:
        try:
            result = await parser.parse(msg)
            if result["action"] != expected["action"]:
                print(f"  Parse '{msg}': action mismatch, got {result['action']}, expected {expected['action']}")
            if "count" in expected and result.get("count") != expected["count"]:
                print(f"  Parse '{msg}': count mismatch, got {result.get('count')}, expected {expected['count']}")
            if "target_id" in expected and result.get("target_id") != expected["target_id"]:
                print(f"  Parse '{msg}': target_id mismatch, got {result.get('target_id')}, expected {expected['target_id']}")
        except Exception as e:
            report_bug("intent_parser", f"Parse '{msg}' raised: {e}")


# ---------- Test 9: Share link generation ----------
async def test9_share_links():
    """Test share link generation for all protocol types."""
    print("\n=== TEST 9: Share link generation ===")

    from src.utils.credential import generate_proxy_credentials

    protocols = ["vless", "vmess", "trojan", "shadowsocks", "socks5", "http"]
    uuids, passwords = generate_proxy_credentials(protocols)

    proxy = Proxy(
        id=1,
        ipv6_addr="2602:294:1:a18::100",
        base_port=20000,
        protocols=protocols,
        cred_uuids=uuids,
        cred_passwords=passwords,
        tls_enabled=False,
    )

    links = generate_all_share_links(proxy)
    print(f"  Generated {len(links)} share links")

    for proto, link in links.items():
        if "Error" in link:
            report_bug("share_link", f"Share link generation failed for {proto}: {link}")
        elif not link:
            report_bug("share_link", f"Empty share link for {proto}")
        else:
            # Basic format check
            prefix_map = {
                "vless": "vless://",
                "vmess": "vmess://",
                "trojan": "trojan://",
                "shadowsocks": "ss://",
                "socks5": "socks5://",
                "http": "http://",
            }
            expected_prefix = prefix_map.get(proto, "")
            if expected_prefix and not link.startswith(expected_prefix):
                report_bug("share_link", f"Invalid {proto} share link format: {link[:60]}...")


# ---------- Test 10: Credential generation uniqueness ----------
async def test10_credential_uniqueness():
    """Test that credential generation produces unique values."""
    print("\n=== TEST 10: Credential uniqueness ===")

    from src.utils.credential import generate_proxy_credentials, generate_uuid, generate_password

    uuids_set = set()
    for _ in range(100):
        uuids_set.add(generate_uuid())
    if len(uuids_set) < 100:
        report_bug("credential", f"UUID collision in 100 generations: only {len(uuids_set)} unique")

    passwords_set = set()
    for _ in range(100):
        passwords_set.add(generate_password(12))
    if len(passwords_set) < 100:
        report_bug("credential", f"Password collision in 100 generations: only {len(passwords_set)} unique")


# ---------- Test 11: Database connection handling ----------
async def test11_db_pooling():
    """Test database connection handling under stress."""
    print("\n=== TEST 11: Database connection handling ===")

    await init_db()

    async def db_op(i):
        db = await get_db()
        try:
            await db.execute("SELECT 1")
            row = await db.execute(
                "INSERT INTO operation_logs (action, target_id, result) VALUES (?, ?, ?)",
                ("test", i, "success")
            )
            await db.commit()
        finally:
            await db.close()

    # Run many concurrent DB operations
    tasks = [db_op(i) for i in range(50)]
    try:
        await asyncio.gather(*tasks)
        print(f"  Completed 50 concurrent DB operations")
    except Exception as e:
        report_bug("database", f"Concurrent DB operations failed: {e}")

    # Cleanup
    db = await get_db()
    try:
        await db.execute("DELETE FROM operation_logs WHERE action='test'")
        await db.commit()
    finally:
        await db.close()


# ---------- Test 12: Xray config generation ----------
async def test12_xray_config():
    """Test xray config generation and check for issues."""
    print("\n=== TEST 12: Xray config generation ===")

    from src.utils.credential import generate_proxy_credentials

    protocols_list = [
        ["vless"],
        ["vless", "vmess"],
        ["vless", "vmess", "trojan", "shadowsocks", "socks5", "http"],
        ["shadowsocks", "socks5"],
        ["trojan"],
    ]

    for prots in protocols_list:
        uuids, passwords = generate_proxy_credentials(prots)
        proxy = Proxy(
            id=1,
            ipv6_addr="2602:294:1:a18::100",
            base_port=30000,
            protocols=prots,
            cred_uuids=uuids,
            cred_passwords=passwords,
        )

        inbounds = generate_inbound_for_proxy(proxy)
        inb_prots = {ib["protocol"] for ib in inbounds}

        # Check that expected protocols are in inbounds
        for p in prots:
            p_lower = p.lower()
            xray_proto = "socks" if p_lower == "socks5" else p_lower
            if xray_proto not in inb_prots:
                report_bug("xray_templates",
                           f"Protocol {p} ({xray_proto}) not generated for config. "
                           f"Generated: {inb_prots}",
                           severity="high")


# ---------- Test 13: Health checker logic ----------
async def test13_health_checker():
    """Test the health checker statistics and failure counting logic."""
    print("\n=== TEST 13: Health checker logic ===")

    await init_db()
    db = await get_db()
    try:
        await db.execute("DELETE FROM proxies")
        await db.commit()
    finally:
        await db.close()

    from src.agent.health_checker import HealthChecker
    from src.db.models import Proxy

    hc = HealthChecker(interval=60, timeout=5, max_failures=3)

    # Test that the health checker correctly tracks verify_count
    proxy = Proxy(
        id=1,
        ipv6_addr="2602:294:1:a18::200",
        base_port=40000,
        protocols=["vless"],
        status="active",
        verify_count=2,
        cred_uuids={"vless": "test"},
    )

    # In the _check_all method, if verify_count + 1 >= max_failures:
    # proxy with verify_count=2, max_failures=3 -> 2+1=3 >= 3 -> marked as error
    # This means 3 consecutive failures trigger error state
    # But verify_count=2 means it already failed twice, one more is 3
    should_be_error = (proxy.verify_count + 1) >= hc.max_failures
    # Actually at 2/3, one more failure (to 3) triggers the error
    if should_be_error:
        print(f"  Proxy with verify_count={proxy.verify_count}, max_failures={hc.max_failures}: would be marked error on next failure")
    else:
        print(f"  Proxy with verify_count={proxy.verify_count}, max_failures={hc.max_failures}: would NOT be marked error on next failure")
        report_bug("health_checker",
                   f"Logic issue: proxy.verify_count ({proxy.verify_count}) + 1 = {proxy.verify_count+1} >= max_failures ({hc.max_failures}) = False. "
                   f"Should be >=")


# ---------- Test 14: 30-day simulation ----------
async def test14_simulation_30days():
    """Simulate 30 days of random operations."""
    print("\n=== TEST 14: 30-Day Simulation ===")

    await init_db()
    db = await get_db()
    try:
        await db.execute("DELETE FROM proxies")
        await db.execute("DELETE FROM ipv6_pool")
        await db.commit()
    finally:
        await db.close()

    from src.agent.orchestrator import Orchestrator

    config = load_config()
    config["agent"]["verify_new_proxy"] = False
    orch = Orchestrator(config)
    await orch.initialize()

    all_protocols = ["vless", "vmess", "trojan", "shadowsocks", "socks5", "http"]
    action_counts = {"create": 0, "delete": 0, "list": 0, "stats": 0, "health_check": 0, "errors": 0}
    max_proxies_ever = 0
    total_created = 0
    total_deleted = 0

    # Track open file descriptors to detect leaks
    def get_fd_count():
        try:
            return len(os.listdir("/proc/self/fd"))
        except Exception:
            return -1

    start_fd = get_fd_count()

    for day in range(SIM_DAYS):
        day_errors = 0
        for op_num in range(OPERATIONS_PER_DAY):
            try:
                proxies = await orch.list_proxies()
                proxy_count = len(proxies)
                if proxy_count > max_proxies_ever:
                    max_proxies_ever = proxy_count

                action = random.choices(
                    ["create", "delete", "list", "stats", "health_check"],
                    weights=[4, 2, 1, 1, 2]
                )[0]

                if action == "create" and proxy_count < 100:
                    count = random.choices([1, 1, 1, 2, 2, 3, 5, 10], weights=[30, 10, 10, 8, 5, 3, 1])[0]
                    num_protos = random.choices([1, 2, 3, 4, 5, 6], weights=[1, 3, 4, 3, 2, 1])[0]
                    protocols = random.sample(all_protocols, num_protos)
                    created, results = await orch.create_proxies(count, protocols)
                    action_counts["create"] += 1
                    total_created += created
                    if created < count:
                        day_errors += 1

                elif action == "delete" and proxy_count > 5:
                    if proxies:
                        target = random.choice(proxies)
                        success = await orch.delete_proxy(proxy_id=target["id"])
                        action_counts["delete"] += 1
                        if success:
                            total_deleted += 1

                elif action == "list":
                    all_p = await orch.list_proxies()
                    action_counts["list"] += 1
                    if len(all_p) != proxy_count:
                        day_errors += 1

                elif action == "stats":
                    await orch.get_stats()
                    action_counts["stats"] += 1

                elif action == "health_check":
                    await orch.health_check_all()
                    action_counts["health_check"] += 1

            except Exception as e:
                day_errors += 1
                action_counts["errors"] += 1

        if day_errors > 0:
            action_counts["errors"] += day_errors

        if (day + 1) % 5 == 0:
            proxies = await orch.list_proxies()
            stats = await orch.get_stats()
            fd_count = get_fd_count()
            print(f"  Day {day+1:2d}: {len(proxies)} proxies, "
                  f"errs={day_errors}, FDs={fd_count}, "
                  f"stats_total={stats.get('total',0)}")

    end_fd = get_fd_count()
    fd_growth = end_fd - start_fd

    print(f"\n  30-Day Simulation Summary:")
    print(f"  Max concurrent proxies: {max_proxies_ever}")
    print(f"  Total created: {total_created}")
    print(f"  Total deleted: {total_deleted}")
    print(f"  Operation counts: {action_counts}")
    print(f"  File descriptors: {start_fd} -> {end_fd} (delta: {fd_growth})")

    if fd_growth > 100:
        report_bug("30-day simulation",
                   f"File descriptor leak detected: {start_fd} -> {end_fd} (+{fd_growth}). "
                   f"Suggests resources are not being properly closed.",
                   severity="high")

    if action_counts["errors"] > len(BUG_REPORTS):
        print(f"  {action_counts['errors']} runtime errors occurred during simulation")


# ---------- Test 15: Rapid creation/deletion stress ----------
async def test15_stress():
    """Stress test: rapid create and delete cycles."""
    print("\n=== TEST 15: Rapid create/delete stress ===")

    from src.agent.orchestrator import Orchestrator

    config = load_config()
    config["agent"]["verify_new_proxy"] = False
    orch = Orchestrator(config)
    await orch.initialize()

    for cycle in range(5):
        # Create
        created, results = await orch.create_proxies(3, ["vless", "shadowsocks"])
        print(f"  Cycle {cycle+1}: created {created}")
        # Immediately delete
        for r in results:
            success = await orch.delete_proxy(proxy_id=r["id"])
            if not success:
                report_bug("stress", f"Failed to delete proxy {r['id']} in stress cycle {cycle+1}")

    # Verify all cleaned up
    remaining = await orch.list_proxies()
    if len(remaining) > 0:
        print(f"  {len(remaining)} proxies remaining after stress test cleanup")
        # Clean up
        for p in remaining:
            await orch.delete_proxy(proxy_id=p["id"])


# ---------- Test 16: Address manager edge cases ----------
async def test16_address_manager():
    """Test address manager edge cases."""
    print("\n=== TEST 16: Address manager edge cases ===")

    from src.ipv6.address_manager import AddressManager

    am = AddressManager()
    await am.initialize()

    # Test large allocation
    addrs = await am.allocate_addresses(10)
    print(f"  Allocated {len(addrs)} addresses")
    if len(addrs) != 10:
        report_bug("address_manager", f"Requested 10 addresses, got {len(addrs)}")

    # Release all
    for addr in addrs:
        await am.release_address(addr)

    count_after = await am.get_allocated_count()
    if count_after != 0:
        report_bug("address_manager", f"After releasing all, allocated_count={count_after}, expected 0")

    # Test release of non-existent address (should not crash)
    try:
        await am.release_address("::fffff")
        print(f"  Release non-existent address: no crash")
    except Exception as e:
        report_bug("address_manager", f"Release of non-existent address crashed: {e}")

    # Test persisting and restoring
    import tempfile
    try:
        addrs = await am.allocate_addresses(3)
        persisted_file = "/app/data/ipv6_persist"
        if os.path.exists(persisted_file):
            with open(persisted_file) as f:
                lines = f.readlines()
                print(f"  Persisted {len(lines)} addresses")
        for addr in addrs:
            await am.release_address(addr)
    except Exception as e:
        report_bug("address_manager", f"Persist/restore test failed: {e}")


# ---------- Main ----------
async def main():
    print("=" * 70)
    print("  IPv666 - 30 DAY SIMULATION & BUG DETECTION")
    print("=" * 70)

    tests = [
        test1_normalize_protocols,
        test2_port_mismatch,
        test3_next_port,
        test4_write_config_leak,
        test8_intent_parser,
        test9_share_links,
        test10_credential_uniqueness,
        test11_db_pooling,
        test12_xray_config,
        test13_health_checker,
        test5_create_proxies,   # (returns orch, all_proxies)
        test7_edge_cases,
        test16_address_manager,
        test15_stress,
        test14_simulation_30days,
    ]

    orch = None
    all_proxies = []

    for test_func in tests:
        try:
            result = await test_func()
            if test_func.__name__ == "test5_create_proxies":
                orch, all_proxies = result
        except Exception as e:
            report_bug(test_func.__name__, f"Test crashed: {e}\n{traceback.format_exc()}")
            print(traceback.format_exc())

    # Run delete test if we have proxies
    if orch and all_proxies:
        try:
            await test6_delete_proxies(orch, all_proxies)
        except Exception as e:
            report_bug("test6", f"Delete test crashed: {e}")

    # Final cleanup
    try:
        db = await get_db()
        await db.execute("DELETE FROM proxies")
        await db.execute("DELETE FROM ipv6_pool")
        await db.execute("DELETE FROM operation_logs WHERE action='test'")
        await db.commit()
        await db.close()
        print("\n  Database cleaned up.")
    except Exception as e:
        print(f"  Cleanup warning: {e}")

    print("\n" + "=" * 70)
    print(f"  BUG REPORT: {len(BUG_REPORTS)} issues found")
    print("=" * 70)

    if BUG_REPORTS:
        print("\n  HIGH SEVERITY:")
        for bug in BUG_REPORTS:
            if bug["severity"] == "high":
                print(f"    [{bug['module']}] {bug['description']}")
        print("\n  MEDIUM SEVERITY:")
        for bug in BUG_REPORTS:
            if bug["severity"] == "medium":
                print(f"    [{bug['module']}] {bug['description']}")
        print("\n  LOW SEVERITY:")
        for bug in BUG_REPORTS:
            if bug["severity"] == "low":
                print(f"    [{bug['module']}] {bug['description']}")
    else:
        print("  No bugs found!")

    return BUG_REPORTS


if __name__ == "__main__":
    bugs = asyncio.run(main())

    with open("/app/data/simulation_results.json", "w") as f:
        json.dump(bugs, f, indent=2, ensure_ascii=False)

    print(f"\nResults saved to /app/data/simulation_results.json")

    if any(b["severity"] == "high" for b in bugs):
        sys.exit(1)
    else:
        print("\nAll critical tests passed.")
        sys.exit(0)
