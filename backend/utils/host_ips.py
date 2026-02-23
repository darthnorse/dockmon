"""
Host IP detection and serialization utilities.

Provides:
- fib_trie parser for detecting host IPs from /proc/net/fib_trie
- Serialization/deserialization for the host_ip database column (JSON array)
"""
import ipaddress
import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def _is_valid_ip(value: str) -> bool:
    """Check if a string is a valid IPv4 or IPv6 address."""
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def get_host_ips_from_fib_trie(proc_path: str = "/proc") -> list[str]:
    """Parse /proc/net/fib_trie for /32 host LOCAL entries.

    Follows the same algorithm as the Go agent's GetHostIPsFromProc().
    Filters out 127.x (loopback) and 169.254.x (link-local).

    Args:
        proc_path: Path to proc filesystem ("/proc" or "/host/proc")

    Returns:
        List of detected IPv4 addresses, deduplicated.
    """
    fib_path = os.path.join(proc_path, "net", "fib_trie")
    try:
        with open(fib_path, "r") as f:
            lines = f.readlines()
    except (OSError, IOError):
        return []

    seen: set[str] = set()
    ips: list[str] = []
    last_ip = ""

    for line in lines:
        stripped = line.strip()

        # Match "|-- X.X.X.X" lines
        if stripped.startswith("|-- "):
            last_ip = stripped[4:]
            continue

        # Match "+-- X.X.X.X" (root level entries have /N suffix - skip those)
        if stripped.startswith("+-- "):
            candidate = stripped[4:]
            if "/" in candidate:
                last_ip = ""
                continue
            last_ip = candidate
            continue

        # Check for "/32 host LOCAL" pattern
        if last_ip and "/32 host LOCAL" in stripped:
            if last_ip.startswith("127.") or last_ip.startswith("169.254."):
                last_ip = ""
                continue
            if not _is_valid_ip(last_ip):
                last_ip = ""
                continue
            if last_ip not in seen:
                seen.add(last_ip)
                ips.append(last_ip)
            last_ip = ""
            continue

        # Reset on non-matching substantive lines
        if stripped and not stripped.startswith("|") and not stripped.startswith("+"):
            last_ip = ""

    return ips


def filter_docker_network_ips(ips: list[str], docker_client) -> list[str]:
    """Remove IPs that fall within Docker/Podman network subnets.

    Queries the Docker daemon for all network subnets and filters out any
    detected IPs that belong to them (bridge gateways, container IPs, etc.).
    Returns the original list unchanged if the Docker query fails.
    """
    if not ips:
        return ips

    subnets = []
    try:
        for network in docker_client.networks.list():
            for config in network.attrs.get('IPAM', {}).get('Config', []):
                subnet = config.get('Subnet')
                if subnet:
                    subnets.append(ipaddress.ip_network(subnet, strict=False))
    except Exception:
        return ips

    if not subnets:
        return ips

    return [ip for ip in ips if not any(ipaddress.ip_address(ip) in subnet for subnet in subnets)]


def deserialize_host_ips(db_value: Optional[str]) -> list[str]:
    """Deserialize host_ip column value to a list of IPs.

    Handles:
    - JSON arrays: '["192.168.1.10", "10.0.0.1"]' -> ["192.168.1.10", "10.0.0.1"]
    - Legacy single IP strings: "192.168.1.10" -> ["192.168.1.10"]
    - JSON-quoted strings: '"192.168.1.10"' -> ["192.168.1.10"]
    - None/empty: None -> []

    Invalid IP strings are silently dropped.
    """
    if not db_value:
        return []

    try:
        parsed = json.loads(db_value)
        if isinstance(parsed, list):
            return [str(ip) for ip in parsed if ip and _is_valid_ip(str(ip))]
        if isinstance(parsed, str) and _is_valid_ip(parsed):
            return [parsed]
        if isinstance(parsed, str):
            return []
    except (json.JSONDecodeError, TypeError):
        pass

    # Fallback: treat as plain string IP (legacy backward compat)
    db_value = db_value.strip()
    if db_value and _is_valid_ip(db_value):
        return [db_value]
    return []


def serialize_host_ips(ips: list[str]) -> Optional[str]:
    """Serialize a list of IPs to JSON array string for database storage.

    Returns None if the list is empty. This is intentionally asymmetric with
    deserialize_host_ips() which returns [] for None -- both represent "no IPs"
    but None avoids storing empty arrays in the database.
    """
    if not ips:
        return None
    return json.dumps(ips)


def serialize_registration_host_ip(registration_data: dict) -> Optional[str]:
    """Extract and serialize host IPs from an agent registration payload.

    Prefers the ``host_ips`` list field sent by new agents, falls back to the
    legacy ``host_ip`` single-string field from older agents.

    Returns a JSON array string suitable for the ``host_ip`` DB column, or None.
    """
    host_ips = registration_data.get("host_ips")
    if host_ips:
        return serialize_host_ips(host_ips)
    host_ip_single = registration_data.get("host_ip")
    if host_ip_single:
        return serialize_host_ips([host_ip_single])
    return None
