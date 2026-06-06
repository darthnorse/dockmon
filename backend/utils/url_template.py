"""URL template resolver for the webui_url_mapping_chain setting.

Templates support two placeholder kinds:
    ${env:NAME}     -> looked up in container.env
    ${label:NAME}   -> looked up in container.labels

If any placeholder cannot be resolved (key missing, value empty, or input dict
is None), the whole template returns None so the chain can fall through. Values
containing control chars are also treated as failed resolutions — env/labels
are container-author-controlled and could otherwise corrupt the resulting URL.
"""
import re
from typing import Optional

_PLACEHOLDER_RE = re.compile(r"\$\{(env|label):([^}]+)\}")
# Reject all ASCII control chars (0x00-0x1F including tab/LF/CR, plus DEL 0x7F)
# AND Unicode line/paragraph separators (NEL U+0085, LS U+2028, PS U+2029) in
# placeholder values. Container env/labels are arbitrary UTF-8 from container
# authors; control chars in resolved URLs enable response-splitting / log-injection
# and break URL parsing. Only space (0x20) and printable chars are accepted.
_CONTROL_CHARS_RE = re.compile("[\x00-\x1f\x7f\u0085\u2028\u2029]")
# Cap resolved URL length. Most browsers tolerate ~2000-2048 chars; longer
# values are almost certainly malformed env data, not legitimate URLs.
MAX_RESOLVED_URL_LENGTH = 2048


def resolve_url_template(
    template: str,
    env: Optional[dict],
    labels: Optional[dict],
) -> Optional[str]:
    """Resolve a single template against a container's env and labels.

    Returns the substituted string, or None if any placeholder is missing,
    empty, contains control characters, or the resolved URL exceeds
    MAX_RESOLVED_URL_LENGTH.
    """
    env = env or {}
    labels = labels or {}
    failed = False

    def _sub(match: re.Match) -> str:
        nonlocal failed
        kind, name = match.group(1), match.group(2)
        source = env if kind == "env" else labels
        value = source.get(name, "")
        if not value or _CONTROL_CHARS_RE.search(value):
            failed = True
            return ""
        return value

    result = _PLACEHOLDER_RE.sub(_sub, template)
    if failed or len(result) > MAX_RESOLVED_URL_LENGTH:
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
