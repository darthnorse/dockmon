"""Helpers for normalizing Docker API timestamps for the frontend."""

import re

_TZ_OFFSET_RE = re.compile(r'[+-]\d{2}:\d{2}$')


def normalize_docker_timestamp(created: str) -> str:
    """Strip a trailing timezone offset and append 'Z' so the frontend reads UTC.

    Docker returns timestamps like '2026-01-03T17:11:27.020018176-07:00'; the
    frontend expects a 'Z' suffix. Already-'Z' and empty values pass through
    unchanged.
    """
    if created and not created.endswith('Z'):
        created = _TZ_OFFSET_RE.sub('Z', created)
    return created
