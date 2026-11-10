"""
Update ordering for containers that share a network namespace.

A dependent (network_mode: container:X) updates before its provider X. The provider's
ID doesn't change when its dependent updates, and the provider finds its dependents
when it runs, so it recreates them on their new images. Going the other way would
remove the ID the dependent's own update was using.
"""

import logging
from typing import List, Optional

from models.docker_models import Container

logger = logging.getLogger(__name__)


def update_layers(containers: List[Container]) -> List[List[Container]]:
    """
    Group containers into layers to update one after another.

    Pass only the containers being updated. A container whose network mode is unknown
    counts as unlinked, so it runs in the first layer.
    """
    dependents_of = {_key(c): set() for c in containers}
    for container in containers:
        provider = _find_provider(container, containers)
        if provider is not None:
            dependents_of[_key(provider)].add(_key(container))

    layers = []
    remaining = {_key(c): c for c in containers}
    while remaining:
        layer = [c for key, c in remaining.items() if dependents_of[key].isdisjoint(remaining)]
        if not layer:
            layer = list(remaining.values())
            names = [c.name for c in layer]
            logger.error(f"Circular network dependency between {names}, updating them together")
        layers.append(layer)
        for container in layer:
            del remaining[_key(container)]
    return layers


def recreated_dependents(provider: Container, containers: List[Container]) -> List[Container]:
    """
    The containers the updater recreates when `provider` is updated, matched the way
    shared/update/dependents.go matches them: by name, short ID or full ID, never a prefix.
    """
    refs = {provider.name, provider.short_id}
    return [
        c for c in containers
        if c.host_id == provider.host_id
        and _key(c) != _key(provider)
        and _names_provider(c.network_mode, refs, provider.short_id)
    ]


def _names_provider(network_mode: Optional[str], refs: set, short_id: str) -> bool:
    if not (network_mode or "").startswith("container:"):
        return False
    ref = network_mode[len("container:"):]
    return ref in refs or (len(ref) == 64 and ref.startswith(short_id))


def _key(container: Container) -> tuple:
    return container.host_id, container.short_id


def _find_provider(container: Container, containers: List[Container]) -> Optional[Container]:
    network_mode = container.network_mode or ""
    if not network_mode.startswith("container:"):
        return None
    ref = network_mode[len("container:"):]
    for candidate in containers:
        if candidate.host_id != container.host_id or _key(candidate) == _key(container):
            continue
        if ref == candidate.name or ref.startswith(candidate.short_id):
            return candidate
    return None
