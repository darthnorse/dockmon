"""
Port collision detection for stack deployments.

Pure module — no Docker calls, no I/O beyond YAML parsing. Callers pass
in a pre-fetched container list; this module reports which of the
stack's requested host-port bindings would collide.

See docs/superpowers/specs/2026-04-22-port-collision-detection-design.md
"""

import logging
import re
from dataclasses import dataclass
from typing import Iterable

import yaml

from deployment.container_utils import get_container_compose_project

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

    Raises:
        ValueError: if `published` is not a valid port number or range.
    """
    published = entry.get("published")
    if published is None:
        return []
    protocol = entry.get("protocol") or "tcp"
    # published can be int or string like "8080" or "8080-8085"
    pub_str = str(published)
    try:
        if "-" in pub_str:
            start_str, end_str = pub_str.split("-", 1)
            start, end = int(start_str), int(end_str)
            if start > end:
                return []
            return [PortSpec(port=p, protocol=protocol) for p in range(start, end + 1)]
        return [PortSpec(port=int(pub_str), protocol=protocol)]
    except ValueError as exc:
        raise ValueError(f"Invalid published port in compose: {pub_str!r}") from exc


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

    if not isinstance(doc, dict):
        return []

    services = doc.get("services") or {}
    if not isinstance(services, dict):
        return []
    seen: set[PortSpec] = set()
    result: list[PortSpec] = []

    for service in services.values():
        if not isinstance(service, dict):
            continue
        ports = service.get("ports")
        if not ports:
            continue
        if not isinstance(ports, list):
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


# Port-string parser for Container.ports entries coming from the monitor cache.
# Shape: "<host_port>:<container_port>[/protocol]" or "<container_port>[/protocol]".
_CACHE_PORT_RE = re.compile(
    r"^(?:(?P<host>\d{1,5}):)?(?P<container>\d{1,5})(?:/(?P<proto>tcp|udp))?$"
)


@dataclass(frozen=True)
class Conflict:
    """A port binding collision against an existing container."""
    port: int
    protocol: str
    container_id: str
    container_name: str


def _parse_cache_port(entry: str) -> PortSpec | None:
    """
    Parse a single Container.ports entry into a PortSpec representing the
    *host-side* binding. Returns None for entries with no host port
    (container-only exposes).
    """
    match = _CACHE_PORT_RE.match(entry.strip())
    if not match:
        return None
    host = match.group("host")
    if host is None:
        return None  # exposed but not bound - nothing to conflict on
    protocol = match.group("proto") or "tcp"
    return PortSpec(port=int(host), protocol=protocol)


def find_port_conflicts(
    requested: list[PortSpec],
    containers: list,
    exclude_project: str | None,
) -> list[Conflict]:
    """
    Return the subset of `requested` port bindings that collide with ports
    already bound by `containers` on the same host.

    Containers whose `com.docker.compose.project` label equals
    `exclude_project` are ignored (self-exclusion on redeploy).

    Args:
        requested: Port bindings the stack is asking for.
        containers: Cached container records from the target host. Each
            must expose `.id`, `.name`, `.ports`, `.labels`.
        exclude_project: Compose project name whose containers should be
            excluded from the baseline. Typically the stack's own name.
    """
    if not requested or not containers:
        return []

    baseline: dict[PortSpec, tuple[str, str]] = {}
    for c in containers:
        if exclude_project and get_container_compose_project(c) == exclude_project:
            continue
        for entry in (c.ports or []):
            spec = _parse_cache_port(entry)
            if spec is None:
                continue
            # First container wins for a given port - if multiple containers
            # somehow bind the same host port/protocol, that's Docker's problem
            # and not ours to deduplicate against.
            baseline.setdefault(spec, (c.id[:12], c.name))

    conflicts: list[Conflict] = []
    for spec in requested:
        match = baseline.get(spec)
        if match is None:
            continue
        cid, cname = match
        conflicts.append(Conflict(
            port=spec.port, protocol=spec.protocol,
            container_id=cid, container_name=cname,
        ))

    return conflicts
