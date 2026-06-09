"""Helpers for a stack's env files: name safety and env_file: directive parsing.

Scope (v1, #205): only same-directory bare filenames are captured/managed.
This bounds an arbitrary-file-read on import and an arbitrary-file-write on
deploy to the compose's own directory.
"""
import os
from typing import List, Tuple

import yaml


def is_safe_env_filename(name: str) -> bool:
    """True if `name` is a bare filename safe to write inside a stack directory.

    A leading './' (allowed by compose for same-dir refs) is tolerated.
    Rejects: empty, non-str, absolute paths, separators, subdirs, '.' and '..',
             surrounding/only whitespace (validated form must match stored form).
    """
    if not name or not isinstance(name, str):
        return False
    candidate = name[2:] if name.startswith("./") else name
    if not candidate or candidate in (".", ".."):
        return False
    # Reject names with leading/trailing whitespace or whitespace-only names.
    # The stored filename is produced by stripping only the leading './', not
    # whitespace, so accepting padded names would cause the validated form to
    # differ from what gets written to disk.
    if candidate != candidate.strip() or not candidate.strip():
        return False
    if "/" in candidate or "\\" in candidate or "\x00" in candidate:
        return False
    if candidate != os.path.basename(candidate):
        return False
    return True


def _normalize(name: str) -> str:
    """Strip a leading './' so the stored filename is bare."""
    return name[2:] if name.startswith("./") else name


def parse_env_file_refs(compose_yaml: str) -> Tuple[List[str], List[str]]:
    """Parse service-level env_file: directives from a compose document.

    Returns (captured, skipped):
      captured: sorted unique bare same-dir filenames (leading './' stripped).
      skipped:  refs that are absolute / subdir / parent-escaping, for reporting.
    Malformed YAML or no services -> ([], []).

    Handles all compose forms: a bare string, a list of strings, and the long
    form ({'path': 'x.env', 'required': bool}).
    """
    try:
        doc = yaml.safe_load(compose_yaml)
    except yaml.YAMLError:
        return [], []
    if not isinstance(doc, dict):
        return [], []
    services = doc.get("services")
    if not isinstance(services, dict):
        return [], []

    captured: set[str] = set()
    skipped: List[str] = []

    def handle(ref) -> None:
        path = ref.get("path") if isinstance(ref, dict) else ref
        if not isinstance(path, str) or not path:
            return
        if is_safe_env_filename(path):
            captured.add(_normalize(path))
        else:
            skipped.append(path)

    for svc in services.values():
        if not isinstance(svc, dict):
            continue
        ef = svc.get("env_file")
        if ef is None:
            continue
        if isinstance(ef, list):
            for ref in ef:
                handle(ref)
        else:
            handle(ef)

    return sorted(captured), skipped
