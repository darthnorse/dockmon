"""URL template resolver for the webui_url_mapping_chain feature (Issue #207).

Templates support two placeholder kinds:
    ${env:NAME}     -> looked up in container.env
    ${label:NAME}   -> looked up in container.labels

If any placeholder cannot be resolved (key missing, value empty, or input dict is None),
the whole template returns None so the chain can fall through to the next template.
"""
import re
from typing import Optional

_PLACEHOLDER_RE = re.compile(r"\$\{(env|label):([^}]+)\}")


def resolve_url_template(
    template: str,
    env: Optional[dict],
    labels: Optional[dict],
) -> Optional[str]:
    """Resolve a single template against a container's env and labels.

    Returns the substituted string, or None if any placeholder is missing/empty.
    """
    env = env or {}
    labels = labels or {}
    failed = False

    def _sub(match: re.Match) -> str:
        nonlocal failed
        kind, name = match.group(1), match.group(2)
        source = env if kind == "env" else labels
        value = source.get(name, "")
        if not value:
            failed = True
            return ""
        return value

    result = _PLACEHOLDER_RE.sub(_sub, template)
    if failed:
        return None
    return result


def resolve_chain(
    chain: Optional[list],
    env: Optional[dict],
    labels: Optional[dict],
) -> Optional[str]:
    """Try each template in order; return the first non-None resolution."""
    if not chain:
        return None
    for template in chain:
        if not isinstance(template, str):
            continue
        result = resolve_url_template(template, env, labels)
        if result:
            return result
    return None
