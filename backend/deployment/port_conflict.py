"""
Port collision detection for stack deployments.

Pure module — no Docker calls, no I/O beyond YAML parsing. Operates on the
monitor's in-memory container cache to surface host-port conflicts before
a stack deploy is submitted.

See docs/superpowers/specs/2026-04-22-port-collision-detection-design.md
"""

import logging
import re
from dataclasses import dataclass
from typing import Iterable

import yaml

logger = logging.getLogger(__name__)

# Short-form pattern: [ip:]host_port[-range][:container_port[-range]][/protocol]
# We only care about the host-port side.
_SHORT_FORM_RE = re.compile(
    r"""^
        (?:(?P<ip>\d{1,3}(?:\.\d{1,3}){3}):)?           # optional ip:
        (?P<host>\d{1,5}(?:-\d{1,5})?)                   # host port or range
        (?::(?P<container>\d{1,5}(?:-\d{1,5})?))?        # optional :container[-range]
        (?:/(?P<proto>tcp|udp))?                          # optional /protocol
        $""",
    re.VERBOSE,
)


@dataclass(frozen=True)
class PortSpec:
    """A normalized host-port binding request."""
    port: int
    protocol: str  # "tcp" | "udp"


def _parse_short_form(entry: str) -> list[PortSpec]:
    """
    Parse a short-form compose port string.

    Returns [] if the string has no host-port side (e.g., "80" alone means
    container-only, Docker auto-assigns the host port — nothing to conflict on).
    """
    entry = entry.strip()
    match = _SHORT_FORM_RE.match(entry)
    if not match:
        logger.debug("Unparseable short-form port entry, skipping: %r", entry)
        return []

    host = match.group("host")
    container = match.group("container")
    protocol = match.group("proto") or "tcp"

    # No container-side → entry is container-port only, Docker auto-assigns host port
    if container is None:
        return []

    # Expand range like "3000-3005"
    if "-" in host:
        start_str, end_str = host.split("-", 1)
        start, end = int(start_str), int(end_str)
        if start > end:
            logger.debug("Inverted port range, skipping: %r", entry)
            return []
        return [PortSpec(port=p, protocol=protocol) for p in range(start, end + 1)]

    return [PortSpec(port=int(host), protocol=protocol)]


def _parse_long_form(entry: dict) -> list[PortSpec]:
    """
    Parse a long-form compose port dict.

    Example: {target: 80, published: 8080, protocol: tcp, mode: host}

    Returns [] if `published` is missing (auto-assign).
    """
    published = entry.get("published")
    if published is None:
        return []
    protocol = entry.get("protocol") or "tcp"
    # published can be int or string like "8080" or "8080-8085"
    pub_str = str(published)
    if "-" in pub_str:
        start_str, end_str = pub_str.split("-", 1)
        start, end = int(start_str), int(end_str)
        if start > end:
            return []
        return [PortSpec(port=p, protocol=protocol) for p in range(start, end + 1)]
    return [PortSpec(port=int(pub_str), protocol=protocol)]


def extract_ports_from_compose(compose_yaml: str) -> list[PortSpec]:
    """
    Parse a compose YAML document and return the deduplicated list of
    (host_port, protocol) pairs the stack would bind on the target host.

    Skips entries without a host-port side (Docker will auto-assign those).

    Raises:
        ValueError: if the YAML is malformed.
    """
    try:
        doc = yaml.safe_load(compose_yaml) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid compose YAML: {exc}") from exc

    services = doc.get("services") or {}
    seen: set[PortSpec] = set()
    result: list[PortSpec] = []

    for service_name, service in services.items():
        if not isinstance(service, dict):
            continue
        ports = service.get("ports")
        if not ports:
            continue
        for entry in ports:
            specs: Iterable[PortSpec]
            if isinstance(entry, dict):
                specs = _parse_long_form(entry)
            else:
                # Can be string or int (compose short form)
                specs = _parse_short_form(str(entry))
            for spec in specs:
                if spec not in seen:
                    seen.add(spec)
                    result.append(spec)

    return result
