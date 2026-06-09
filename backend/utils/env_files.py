"""Helpers for a stack's env files: name safety and env_file: directive parsing.

Scope (v1, #205): only same-directory bare filenames are captured/managed.
This bounds an arbitrary-file-read on import and an arbitrary-file-write on
deploy to the compose's own directory.
"""
import os
import re
from typing import List, Tuple

import yaml

# Size cap for reading/discovering an env file. A file named like an env file
# but larger than this (e.g. mislabeled bind-mount data) is never read or
# surfaced.
MAX_ENV_FILE_BYTES = 1024 * 1024


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


def is_env_filename(name: str) -> bool:
    """True if `name` follows an env-file naming convention DockMon manages.

    Matches the conventional '.env', dotfile-suffixed names ('.env.prod',
    '.env.staging'), and '*.env' names ('.db.env', 'prod.env'). Used to
    discover env files that exist on disk but are not (currently) referenced
    by an env_file: directive, so an env-swap workflow can keep editing the
    inactive files. This is the naming convention only; path-safety is checked
    separately via is_safe_env_filename.
    """
    if not name or not isinstance(name, str):
        return False
    return name == ".env" or name.startswith(".env.") or name.endswith(".env")


def normalize_env_filename(name: str) -> str:
    """Strip a leading './' so the stored filename is bare.

    A leading './' is the compose same-dir form; the stored/managed filename is
    always the bare basename. Callers that derive an on-disk path or compare
    against the managed set must normalize first so the forms agree.
    """
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
    except (yaml.YAMLError, RecursionError):
        # RecursionError: deeply-nested YAML exhausts the parser's stack. Treat
        # any unparseable document as having no managed env files rather than
        # letting the exception escape to the caller.
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
            captured.add(normalize_env_filename(path))
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


# A single leading interpolation segment (${VAR}/ or $VAR/) on a bind source.
# Compose resolves ${PWD}/x relative to the compose dir, so the bare basename is
# still a same-dir file we must protect.
_VAR_PREFIX_RE = re.compile(r"^(?:\$\{[^}/]+\}|\$[A-Za-z_][A-Za-z0-9_]*)/(.+)$")


def parse_bind_mount_sources(compose_yaml: str) -> set:
    """Best-effort set of bare same-dir filenames used as bind-mount sources.

    Scans each service's volumes: (short 'SOURCE:TARGET[:MODE]' and long
    {source: ..., type: bind}) and the top-level volumes: map (local bind
    volumes via driver_opts.device), returning sources that resolve to a bare
    same-dir filename (per is_safe_env_filename), normalized. A leading ${VAR}/
    or $VAR/ interpolation prefix is stripped first, so a same-dir source written
    as ${PWD}/app.env is still recognized. Absolute and subdir paths (which point
    outside the stack dir's top level, so no discovered file can collide) and
    named volumes are ignored. Malformed YAML -> set().

    This is a defensive exclusion for env-file discovery: don't surface (or let
    delete) a data file the compose bind-mounts. Over-capturing a
    coincidentally-named source only hides an env tab -- the safe direction.
    """
    try:
        doc = yaml.safe_load(compose_yaml)
    except (yaml.YAMLError, RecursionError):
        return set()
    if not isinstance(doc, dict):
        return set()

    sources: set = set()

    def add_source(src) -> None:
        if not isinstance(src, str) or not src:
            return
        # Reduce a ${PWD}/app.env style source to the bare 'app.env' it names.
        m = _VAR_PREFIX_RE.match(src)
        candidate = m.group(1) if m else src
        if is_safe_env_filename(candidate):
            sources.add(normalize_env_filename(candidate))

    services = doc.get("services")
    if isinstance(services, dict):
        for svc in services.values():
            if not isinstance(svc, dict):
                continue
            vols = svc.get("volumes")
            if not isinstance(vols, list):
                continue
            for vol in vols:
                if isinstance(vol, str):
                    # short syntax: SOURCE:TARGET[:MODE] -> SOURCE is first field
                    add_source(vol.split(":", 1)[0])
                elif isinstance(vol, dict):
                    # long syntax: only bind mounts have a path source
                    if vol.get("type", "bind") == "bind":
                        add_source(vol.get("source"))

    # Top-level local bind volumes: a named volume that is really a bind to a
    # same-dir file (volumes.<name>.driver_opts.device: ./runtime.env).
    top_volumes = doc.get("volumes")
    if isinstance(top_volumes, dict):
        for vol in top_volumes.values():
            if isinstance(vol, dict):
                opts = vol.get("driver_opts")
                if isinstance(opts, dict):
                    add_source(opts.get("device"))

    return sources
