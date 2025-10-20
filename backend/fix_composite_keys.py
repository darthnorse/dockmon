#!/usr/bin/env python3
"""
Automated script to replace all composite key constructions with utility functions.
This ensures DRY principle and centralized validation.
"""

import re
import sys

# Files and their required imports
REPLACEMENTS = {
    'docker_monitor/state_manager.py': {
        'import_line': 'from utils.keys import make_composite_key',
        'import_after': 'import logging',
        'patterns': [
            (r'container_key = f"\{host_id\}:\{container_id\}"', 'container_key = make_composite_key(host_id, container_id)'),
        ]
    },
    'docker_monitor/operations.py': {
        'import_line': 'from utils.keys import make_composite_key',
        'import_after': 'from typing import',
        'patterns': [
            (r'container_key = f"\{host_id\}:\{container_id\}"', 'container_key = make_composite_key(host_id, container_id)'),
        ]
    },
    'docker_monitor/monitor.py': {
        'import_line': 'from utils.keys import make_composite_key',
        'import_after': 'import logging',
        'patterns': [
            (r'container_key = f"\{container\.host_id\}:\{container\.short_id\}"', 'container_key = make_composite_key(container.host_id, container.short_id)'),
            (r'container_key = f"\{host_id\}:\{container_id\}"', 'container_key = make_composite_key(host_id, container_id)'),
            (r'key = f"\{container\.host_id\}:\{container\.name\}"', 'key = make_composite_key(container.host_id, container.name)'),
            (r'key = f"\{alert_container\.host_id\}:\{alert_container\.container_name\}"', 'key = make_composite_key(alert_container.host_id, alert_container.container_name)'),
            (r'container_key = f"\{config\.host_id\}:\{config\.container_id\}"', 'container_key = make_composite_key(config.host_id, config.container_id)'),
        ]
    },
    'docker_monitor/container_discovery.py': {
        'import_line': 'from utils.keys import make_composite_key',
        'import_after': 'import logging',
        'patterns': [
            (r'composite_key = f"\{container\.host_id\}:\{container\.short_id\}"', 'composite_key = make_composite_key(container.host_id, container.short_id)'),
        ]
    },
    'alerts/evaluation_service.py': {
        'import_line': 'from utils.keys import make_composite_key',
        'import_after': 'import logging',
        'patterns': [
            (r'composite_key = f"\{host_id\}:\{container_id\}"', 'composite_key = make_composite_key(host_id, container_id)'),
        ]
    },
    'database.py': {
        'import_line': 'from utils.keys import make_composite_key',
        'import_after': 'from datetime import datetime, timezone',
        'patterns': [
            (r'container_key = f"\{host_id\}:\{container_id\}"', 'container_key = make_composite_key(host_id, container_id)'),
        ]
    },
}


def add_import_if_missing(content: str, import_line: str, import_after: str) -> str:
    """Add import line if not already present."""
    if import_line in content:
        return content

    # Find the line to insert after
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if import_after in line:
            # Insert after this line
            lines.insert(i + 1, import_line)
            return '\n'.join(lines)

    # Fallback: add at top after first import section
    for i, line in enumerate(lines):
        if line.startswith('import ') or line.startswith('from '):
            continue
        if line.strip() == '':
            lines.insert(i, import_line)
            return '\n'.join(lines)

    return content


def replace_patterns(content: str, patterns: list) -> tuple[str, int]:
    """Replace all patterns in content."""
    count = 0
    for pattern, replacement in patterns:
        new_content = re.sub(pattern, replacement, content)
        if new_content != content:
            count += content.count(re.findall(pattern, content)[0]) if re.findall(pattern, content) else 0
            content = new_content
            count = len(re.findall(pattern.replace('\\', ''), content))  # Count matches

    return content, count


def main():
    total_replaced = 0

    for file_path, config in REPLACEMENTS.items():
        full_path = f'/Users/patrikrunald/Documents/CodeProjects/dockmon/backend/{file_path}'

        try:
            with open(full_path, 'r') as f:
                content = f.read()

            # Add import
            content = add_import_if_missing(content, config['import_line'], config['import_after'])

            # Replace patterns
            content, count = replace_patterns(content, config['patterns'])

            # Write back
            with open(full_path, 'w') as f:
                f.write(content)

            print(f"✅ {file_path}: {count} replacements")
            total_replaced += count

        except FileNotFoundError:
            print(f"❌ {file_path}: File not found")
        except Exception as e:
            print(f"❌ {file_path}: Error - {e}")

    print(f"\n🎉 Total replacements: {total_replaced}")


if __name__ == '__main__':
    main()
