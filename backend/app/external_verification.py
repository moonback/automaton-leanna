"""Read-only checks for explicitly allowed local external effects.

Network probes are restricted to loopback addresses to prevent SSRF and
accidental access to LAN or Internet resources.
"""
import ipaddress
import socket
from urllib.parse import urlsplit

import httpx


ALLOWED_KINDS = {"http_status", "tcp_port_open"}
MAX_CHECKS = 10
DEFAULT_TIMEOUT = 1.5


def _loopback_host(host):
    if not isinstance(host, str) or not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def normalize_checks(checks):
    if not isinstance(checks, list) or not 1 <= len(checks) <= MAX_CHECKS:
        raise ValueError(f"Fournis entre 1 et {MAX_CHECKS} contrôles externes.")
    normalized = []
    for check in checks:
        if not isinstance(check, dict):
            raise ValueError("Contrôle externe invalide.")
        kind = check.get("kind")
        if kind == "http_status":
            url = check.get("url")
            if not isinstance(url, str) or len(url) > 2048:
                raise ValueError("http_status exige une URL locale valide.")
            parsed = urlsplit(url)
            if (parsed.scheme != "http" or not _loopback_host(parsed.hostname)
                    or parsed.username is not None or parsed.password is not None
                    or parsed.fragment):
                raise ValueError("Les contrôles HTTP sont limités aux URL HTTP de loopback.")
            try:
                port = parsed.port
            except ValueError as exc:
                raise ValueError("Port HTTP invalide.") from exc
            if port is not None and not 1 <= port <= 65535:
                raise ValueError("Port HTTP invalide.")
            expected = check.get("expected_status", 200)
            if isinstance(expected, bool) or not isinstance(expected, int) or not 100 <= expected <= 599:
                raise ValueError("expected_status doit être un code HTTP entre 100 et 599.")
            normalized.append({"kind": kind, "url": url, "expected_status": expected})
        elif kind == "tcp_port_open":
            host = check.get("host", "127.0.0.1")
            port = check.get("port")
            timeout_ms = check.get("timeout_ms", 1500)
            if not _loopback_host(host):
                raise ValueError("Les sondes TCP sont limitées aux adresses loopback.")
            if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
                raise ValueError("port doit être un entier entre 1 et 65535.")
            if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or not 100 <= timeout_ms <= 2000:
                raise ValueError("timeout_ms doit être compris entre 100 et 2000.")
            normalized.append({"kind": kind, "host": host, "port": port, "timeout_ms": timeout_ms})
        else:
            raise ValueError(f"Type de contrôle externe non autorisé : {kind}")
    return normalized


def verify_external_checks(checks):
    normalized = normalize_checks(checks)
    results = []
    for index, check in enumerate(normalized):
        item = {**check, "index": index, "passed": False}
        try:
            if check["kind"] == "http_status":
                with httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=False, trust_env=False) as client:
                    response = client.get(check["url"])
                item["observed_status"] = response.status_code
                item["passed"] = response.status_code == check["expected_status"]
                item["message"] = (
                    "Code HTTP conforme." if item["passed"]
                    else f"Code HTTP observé : {response.status_code}, attendu : {check['expected_status']}."
                )
            else:
                with socket.create_connection(
                    (check["host"], check["port"]),
                    timeout=check["timeout_ms"] / 1000,
                ):
                    pass
                item["passed"] = True
                item["message"] = "Port TCP local accessible."
        except (httpx.HTTPError, OSError, ValueError) as exc:
            item["message"] = f"Contrôle externe impossible : {str(exc)[:500]}"
        results.append(item)
    passed = sum(1 for item in results if item["passed"])
    return {
        "passed": passed,
        "failed": len(results) - passed,
        "total": len(results),
        "success": passed == len(results),
        "checks": results,
    }
