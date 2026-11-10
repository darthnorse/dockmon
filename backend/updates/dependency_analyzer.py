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
    return [
        c for c in containers
        if c.host_id == provider.host_id
        and _key(c) != _key(provider)
        and _names_provider(network_ref_of(c), provider)
    ]


def _names_provider(ref: Optional[str], provider: Container) -> bool:
    if ref is None:
        return False
    return ref in (provider.name, provider.short_id) or (len(ref) == 64 and ref.startswith(provider.short_id))


def network_ref_of(container: Container) -> Optional[str]:
    """The X of network_mode container:X, or None."""
    network_mode = container.network_mode or ""
    if not network_mode.startswith("container:"):
        return None
    return network_mode[len("container:"):]


def _key(container: Container) -> tuple:
    return container.host_id, container.short_id


def _find_provider(container: Container, containers: List[Container]) -> Optional[Container]:
    ref = network_ref_of(container)
    if ref is None:
        return None
    for candidate in containers:
        if candidate.host_id != container.host_id or _key(candidate) == _key(container):
            continue
        if ref == candidate.name or ref.startswith(candidate.short_id):
            return candidate
    return None
