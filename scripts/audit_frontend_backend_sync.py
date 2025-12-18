#!/usr/bin/env python3
"""
Frontend-Backend Sync Audit Script

Finds mismatches between frontend constants and backend handlers/validators.
Run from project root: python scripts/audit_frontend_backend_sync.py
"""

import os
import re
import json
from pathlib import Path
from typing import Set, Dict, List, Tuple
from dataclasses import dataclass, field

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
FRONTEND_DIR = PROJECT_ROOT / "ui" / "src"
BACKEND_DIR = PROJECT_ROOT / "backend"


@dataclass
class AuditResult:
    category: str
    frontend_values: Set[str] = field(default_factory=set)
    backend_values: Set[str] = field(default_factory=set)
    backend_locations: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def missing_in_backend(self) -> Set[str]:
        return self.frontend_values - self.backend_values

    @property
    def missing_in_frontend(self) -> Set[str]:
        return self.backend_values - self.frontend_values


def extract_frontend_rule_kinds() -> Set[str]:
    """Extract kind values from RULE_KINDS in AlertRuleFormModal.tsx"""
    kinds = set()
    modal_path = FRONTEND_DIR / "features" / "alerts" / "components" / "AlertRuleFormModal.tsx"

    if not modal_path.exists():
        print(f"WARNING: {modal_path} not found")
        return kinds

    content = modal_path.read_text()
    # Match: value: 'kind_name'
    matches = re.findall(r"value:\s*['\"]([^'\"]+)['\"]", content)

    # Filter to just rule kinds (skip operators, channels, etc.)
    # Rule kinds are in the RULE_KINDS array which comes before OPERATORS
    rule_kinds_section = content.split("const OPERATORS")[0] if "const OPERATORS" in content else content
    kind_matches = re.findall(r"value:\s*['\"]([a-z_]+)['\"]", rule_kinds_section)

    # Filter out non-kind values
    non_kinds = {'>=', '<=', '>', '<', '==', '!=', 'host', 'container',
                 'pushover', 'telegram', 'discord', 'slack', 'gotify', 'ntfy', 'smtp', 'webhook',
                 'critical', 'error', 'warning', 'info', 'open', 'snoozed', 'resolved',
                 'all', 'should_run', 'on_demand'}

    for match in kind_matches:
        if match not in non_kinds and not match.startswith('>') and not match.startswith('<'):
            kinds.add(match)

    return kinds


def extract_frontend_severities() -> Set[str]:
    """Extract severity values from frontend"""
    severities = set()

    # Check AlertRulesPage.tsx for SEVERITY_OPTIONS
    page_path = FRONTEND_DIR / "features" / "alerts" / "AlertRulesPage.tsx"
    if page_path.exists():
        content = page_path.read_text()
        # Look for severity filter options
        matches = re.findall(r"value:\s*['\"]([^'\"]+)['\"].*?(?:critical|error|warning|info)", content, re.IGNORECASE)
        for match in matches:
            if match.lower() in ['critical', 'error', 'warning', 'info']:
                severities.add(match.lower())

    # Also check types file
    types_path = FRONTEND_DIR / "types" / "alerts.ts"
    if types_path.exists():
        content = types_path.read_text()
        match = re.search(r"AlertSeverity\s*=\s*['\"]([^'\"]+)['\"](?:\s*\|\s*['\"]([^'\"]+)['\"])*", content)
        if match:
            severities.update(s.strip("'\"") for s in re.findall(r"['\"]([^'\"]+)['\"]", match.group(0)))

    return severities or {'info', 'warning', 'error', 'critical'}


def extract_frontend_channels() -> Set[str]:
    """Extract notification channel values from frontend"""
    channels = set()
    modal_path = FRONTEND_DIR / "features" / "alerts" / "components" / "AlertRuleFormModal.tsx"

    if modal_path.exists():
        content = modal_path.read_text()
        # Look for NOTIFICATION_CHANNELS section
        if "NOTIFICATION_CHANNELS" in content or "notify_channels" in content:
            # Find the channels array
            channel_section = re.search(r"(?:NOTIFICATION_CHANNELS|const.*channels).*?\[([^\]]+)\]", content, re.DOTALL)
            if channel_section:
                matches = re.findall(r"value:\s*['\"]([^'\"]+)['\"]", channel_section.group(1))
                channels.update(matches)

    # Also check ChannelForm.tsx
    channel_form_path = FRONTEND_DIR / "features" / "alerts" / "components" / "ChannelForm.tsx"
    if channel_form_path.exists():
        content = channel_form_path.read_text()
        matches = re.findall(r"value:\s*['\"]([^'\"]+)['\"]", content)
        for m in matches:
            if m in ['telegram', 'discord', 'slack', 'pushover', 'gotify', 'ntfy', 'smtp', 'webhook', 'email']:
                channels.add(m)

    return channels


def extract_frontend_operators() -> Set[str]:
    """Extract operator values from frontend"""
    operators = set()
    modal_path = FRONTEND_DIR / "features" / "alerts" / "components" / "AlertRuleFormModal.tsx"

    if modal_path.exists():
        content = modal_path.read_text()
        # Look for OPERATORS array
        if "OPERATORS" in content:
            op_section = re.search(r"(?:const OPERATORS|OPERATORS)\s*=\s*\[([^\]]+)\]", content, re.DOTALL)
            if op_section:
                matches = re.findall(r"value:\s*['\"]([^'\"]+)['\"]", op_section.group(1))
                operators.update(matches)

    return operators


def search_backend_kind_checks() -> Tuple[Set[str], Dict[str, List[str]]]:
    """Search backend for all kind checks and return kinds + locations"""
    kinds = set()
    locations = {}

    patterns = [
        r'kind\s*==\s*["\']([^"\']+)["\']',
        r'kind\s*in\s*\[([^\]]+)\]',
        r'\.kind\s*==\s*["\']([^"\']+)["\']',
        r'\.kind\s*in\s*\[([^\]]+)\]',
        r'kinds_to_clear\s*=\s*\[([^\]]+)\]',
    ]

    for py_file in BACKEND_DIR.rglob("*.py"):
        if "__pycache__" in str(py_file) or "test_" in py_file.name:
            continue

        try:
            content = py_file.read_text()
            rel_path = str(py_file.relative_to(PROJECT_ROOT))

            for i, line in enumerate(content.split('\n'), 1):
                for pattern in patterns:
                    matches = re.findall(pattern, line)
                    for match in matches:
                        # Handle list format
                        if ',' in match or "'" in match or '"' in match:
                            items = re.findall(r'["\']([^"\']+)["\']', match)
                            for item in items:
                                kinds.add(item)
                                loc = f"{rel_path}:{i}"
                                if item not in locations:
                                    locations[item] = []
                                locations[item].append(loc)
                        else:
                            kinds.add(match)
                            loc = f"{rel_path}:{i}"
                            if match not in locations:
                                locations[match] = []
                            locations[match].append(loc)
        except Exception as e:
            print(f"Error reading {py_file}: {e}")

    return kinds, locations


def search_backend_validator_sets() -> Dict[str, Tuple[Set[str], str]]:
    """Extract validator constant sets"""
    results = {}
    validator_path = BACKEND_DIR / "alerts" / "validator.py"

    if not validator_path.exists():
        return results

    content = validator_path.read_text()

    # Find set definitions
    patterns = [
        (r"VALID_SEVERITIES\s*=\s*\{([^}]+)\}", "severities"),
        (r"VALID_OPERATORS\s*=\s*\{([^}]+)\}", "operators"),
        (r"VALID_NOTIFICATION_CHANNELS\s*=\s*\{([^}]+)\}", "channels"),
        (r"VALID_SCOPES\s*=\s*\{([^}]+)\}", "scopes"),
    ]

    for pattern, name in patterns:
        match = re.search(pattern, content)
        if match:
            items = re.findall(r'["\']([^"\']+)["\']', match.group(1))
            results[name] = (set(items), str(validator_path.relative_to(PROJECT_ROOT)))

    return results


def search_pydantic_patterns() -> Dict[str, Tuple[Set[str], str]]:
    """Extract patterns from Pydantic models"""
    results = {}

    files_to_check = [
        BACKEND_DIR / "models" / "settings_models.py",
        BACKEND_DIR / "alerts" / "api.py",
    ]

    for file_path in files_to_check:
        if not file_path.exists():
            continue

        content = file_path.read_text()
        rel_path = str(file_path.relative_to(PROJECT_ROOT))

        # Find pattern definitions for severity
        sev_match = re.search(r'severity.*pattern\s*=\s*["\'][\^]?\(?([^"\']+?)\)?[\$]?["\']', content)
        if sev_match:
            # Clean up the pattern - remove regex anchors and grouping
            pattern_str = sev_match.group(1).rstrip(')$').lstrip('^(')
            items = [i.strip(')$^(') for i in pattern_str.split('|')]
            key = f"severity_pattern_{file_path.stem}"
            results[key] = (set(items), rel_path)

        # Find pattern definitions for operator
        op_match = re.search(r'operator.*pattern\s*=\s*["\'][\^]?\(?([^"\']+?)\)?[\$]?["\']', content)
        if op_match:
            # Clean up the pattern - remove regex anchors and grouping
            pattern_str = op_match.group(1).rstrip(')$').lstrip('^(')
            items = [i.strip(')$^(') for i in pattern_str.split('|')]
            key = f"operator_pattern_{file_path.stem}"
            results[key] = (set(items), rel_path)

    return results


def print_section(title: str):
    print(f"\n{'=' * 60}")
    print(f" {title}")
    print('=' * 60)


def print_result(result: AuditResult):
    print(f"\n--- {result.category} ---")
    print(f"Frontend: {sorted(result.frontend_values)}")
    print(f"Backend:  {sorted(result.backend_values)}")

    if result.missing_in_backend:
        print(f"\n  ❌ MISSING IN BACKEND: {sorted(result.missing_in_backend)}")
        print("     These frontend values have no backend handler!")

    if result.missing_in_frontend:
        print(f"\n  ⚠️  Backend-only (not in frontend): {sorted(result.missing_in_frontend)}")

    if not result.missing_in_backend and not result.missing_in_frontend:
        print("\n  ✅ All values match!")


def main():
    print_section("Frontend-Backend Sync Audit")
    print(f"Project root: {PROJECT_ROOT}")

    issues_found = 0

    # 1. Audit Rule Kinds
    print_section("1. RULE KINDS")
    frontend_kinds = extract_frontend_rule_kinds()
    backend_kinds, kind_locations = search_backend_kind_checks()

    # Filter backend kinds to only alert-related ones
    alert_related_kinds = {k for k in backend_kinds if any(x in k for x in
        ['cpu', 'memory', 'disk', 'container', 'host', 'update', 'health', 'unhealthy', 'stopped', 'restart'])}

    result = AuditResult(
        category="Rule Kinds",
        frontend_values=frontend_kinds,
        backend_values=alert_related_kinds,
        backend_locations=kind_locations
    )
    print_result(result)

    if result.missing_in_backend:
        issues_found += len(result.missing_in_backend)
        print("\n  Backend locations for reference:")
        for kind in sorted(result.backend_values)[:10]:
            if kind in kind_locations:
                print(f"    {kind}: {kind_locations[kind][:2]}")

    # 2. Audit Severities
    print_section("2. SEVERITIES")
    frontend_severities = extract_frontend_severities()
    validator_sets = search_backend_validator_sets()
    pydantic_patterns = search_pydantic_patterns()

    if 'severities' in validator_sets:
        result = AuditResult(
            category="Severities (validator.py)",
            frontend_values=frontend_severities,
            backend_values=validator_sets['severities'][0]
        )
        print_result(result)
        if result.missing_in_backend:
            issues_found += len(result.missing_in_backend)

    for key, (values, path) in pydantic_patterns.items():
        if 'severity' in key:
            result = AuditResult(
                category=f"Severities ({path})",
                frontend_values=frontend_severities,
                backend_values=values
            )
            print_result(result)
            if result.missing_in_backend:
                issues_found += len(result.missing_in_backend)

    # 3. Audit Notification Channels
    print_section("3. NOTIFICATION CHANNELS")
    frontend_channels = extract_frontend_channels()

    if 'channels' in validator_sets:
        result = AuditResult(
            category="Channels (validator.py)",
            frontend_values=frontend_channels,
            backend_values=validator_sets['channels'][0]
        )
        print_result(result)
        if result.missing_in_backend:
            issues_found += len(result.missing_in_backend)

    # 4. Audit Operators
    print_section("4. OPERATORS")
    frontend_operators = extract_frontend_operators()

    if 'operators' in validator_sets:
        result = AuditResult(
            category="Operators (validator.py)",
            frontend_values=frontend_operators,
            backend_values=validator_sets['operators'][0]
        )
        print_result(result)
        if result.missing_in_backend:
            issues_found += len(result.missing_in_backend)

    for key, (values, path) in pydantic_patterns.items():
        if 'operator' in key:
            result = AuditResult(
                category=f"Operators ({path})",
                frontend_values=frontend_operators,
                backend_values=values
            )
            print_result(result)
            if result.missing_in_backend:
                issues_found += len(result.missing_in_backend)

    # Summary
    print_section("SUMMARY")
    if issues_found > 0:
        print(f"\n❌ Found {issues_found} potential issue(s) requiring attention")
        print("\nRecommendations:")
        print("1. Add missing backend handlers for frontend kinds")
        print("2. Update validator sets to match frontend options")
        print("3. Consider creating a shared constants file")
    else:
        print("\n✅ All frontend values have corresponding backend handlers!")

    return issues_found


if __name__ == "__main__":
    exit(main())
