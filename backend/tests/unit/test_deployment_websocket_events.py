"""
TDD Tests for Deployment WebSocket Event Structure (Phase 3.4)

Tests verify that deployment progress events match the spec's nested structure
with overall_percent, stage, stage_percent, and layer-by-layer progress.

Spec Reference: Section 6.2 (lines 1090-1180)
Gap Analysis: Issue #4 - WebSocket Event Structure

Pattern: Static code analysis (like Phase 3.3) to avoid import issues during package initialization
"""

import os
import re


def _get_executor_file_path():
    """Get path to executor.py"""
    return os.path.join(os.path.dirname(__file__), '../../deployment/executor.py')


def _read_emit_event_method():
    """Read the _emit_deployment_event method from executor.py"""
    with open(_get_executor_file_path(), 'r') as f:
        content = f.read()

    # Find the _emit_deployment_event method
    match = re.search(
        r'async def _emit_deployment_event\(.*?\):.*?(?=\n    async def |$)',
        content,
        re.DOTALL
    )

    if match:
        return match.group(0)
    return None


# ========== Test 1: Nested Progress Structure ==========

def test_event_payload_uses_nested_progress_object():
    """
    WebSocket event MUST have nested 'progress' object, not flat structure.

    Spec requires:
    {
      "type": "deployment_progress",
      "deployment_id": "...",
      "progress": {
        "overall_percent": 25,
        "stage": "Pulling image",
        "stage_percent": 60
      }
    }

    NOT flat:
    {
      "progress_percent": 25,  # WRONG
      "current_stage": "..."   # WRONG
    }
    """
    method_code = _read_emit_event_method()

    assert method_code is not None, "Could not find _emit_deployment_event method"

    # SPEC REQUIREMENT: Must create nested 'progress' object
    assert "'progress':" in method_code or '"progress":' in method_code, (
        "WebSocket event must have nested 'progress' object.\n\n"
        "Expected structure:\n"
        "  payload = {\n"
        "    'progress': {\n"
        "      'overall_percent': ...,\n"
        "      'stage': ...,\n"
        "      'stage_percent': ...\n"
        "    }\n"
        "  }\n\n"
        "This is REQUIRED by spec Section 6.2 (lines 1116-1145)"
    )

    # ANTI-PATTERN: Should NOT use flat fields at top level
    # Check if progress_percent is being set directly in payload
    flat_progress_pattern = r"['\"]progress_percent['\"]:\s*deployment\.progress_percent"
    if re.search(flat_progress_pattern, method_code):
        assert False, (
            "Event uses FLAT 'progress_percent' field instead of nested 'progress.overall_percent'.\n\n"
            "WRONG (current):\n"
            "  payload = {\n"
            "    'progress_percent': deployment.progress_percent  # FLAT\n"
            "  }\n\n"
            "CORRECT (spec-compliant):\n"
            "  payload = {\n"
            "    'progress': {\n"
            "      'overall_percent': deployment.progress_percent  # NESTED\n"
            "    }\n"
            "  }"
        )


# ========== Test 2: Progress Object Contains Required Fields ==========

def test_progress_object_contains_overall_percent():
    """progress object must contain 'overall_percent' field"""
    method_code = _read_emit_event_method()

    assert method_code is not None

    # Must have overall_percent in progress object
    # Pattern: 'progress': { ... 'overall_percent': ...
    has_overall_percent = (
        "'overall_percent'" in method_code or
        '"overall_percent"' in method_code
    )

    assert has_overall_percent, (
        "progress object must contain 'overall_percent' field.\n\n"
        "Expected:\n"
        "  'progress': {\n"
        "    'overall_percent': deployment.progress_percent,\n"
        "    ...\n"
        "  }"
    )


def test_progress_object_contains_stage():
    """progress object must contain 'stage' field (human-readable description)"""
    method_code = _read_emit_event_method()

    assert method_code is not None

    # Must have stage in progress object
    has_stage = (
        "'stage'" in method_code or
        '"stage"' in method_code
    )

    assert has_stage, (
        "progress object must contain 'stage' field.\n\n"
        "Expected:\n"
        "  'progress': {\n"
        "    'stage': deployment.current_stage,\n"
        "    ...\n"
        "  }\n\n"
        "The 'stage' field is a human-readable description like 'Pulling image nginx:1.25'."
    )


def test_progress_object_contains_stage_percent():
    """progress object must contain 'stage_percent' field (0-100 within current stage)"""
    method_code = _read_emit_event_method()

    assert method_code is not None

    # Must have stage_percent in progress object
    has_stage_percent = (
        "'stage_percent'" in method_code or
        '"stage_percent"' in method_code
    )

    assert has_stage_percent, (
        "progress object must contain 'stage_percent' field.\n\n"
        "Expected:\n"
        "  'progress': {\n"
        "    'stage_percent': getattr(deployment, 'stage_percent', 0),\n"
        "    ...\n"
        "  }\n\n"
        "The 'stage_percent' field shows progress within the current stage (0-100%).\n"
        "Example: If pulling_image stage is 45% done, stage_percent = 45.\n\n"
        "NOTE: deployment model doesn't have stage_percent field yet - that's expected for RED phase.\n"
        "Use getattr() with default 0 until field is added to model."
    )


# ========== Test 3: No Flat Fields in Top-Level Payload ==========

def test_no_flat_progress_percent_field():
    """Event should NOT have flat 'progress_percent' field"""
    method_code = _read_emit_event_method()

    assert method_code is not None

    # Check if progress_percent is in payload dict at top level
    # Pattern: payload = { ... 'progress_percent': ...
    # This is WRONG - should be nested in 'progress' object

    lines = method_code.split('\n')
    in_payload_dict = False
    payload_level = 0

    for line in lines:
        # Track when we're inside payload dict
        if 'payload = {' in line:
            in_payload_dict = True
            payload_level = line.count('{') - line.count('}')
            continue

        if in_payload_dict:
            payload_level += line.count('{') - line.count('}')

            # If we're at top level of payload dict (not nested)
            if payload_level == 1:
                if "'progress_percent':" in line or '"progress_percent":' in line:
                    assert False, (
                        f"Found flat 'progress_percent' field at line: {line.strip()}\n\n"
                        f"WRONG: 'progress_percent' should NOT be at top level of payload.\n"
                        f"CORRECT: Use nested 'progress.overall_percent' instead.\n\n"
                        f"Replace:\n"
                        f"  payload = {{\n"
                        f"    'progress_percent': deployment.progress_percent,  # WRONG\n"
                        f"  }}\n\n"
                        f"With:\n"
                        f"  payload = {{\n"
                        f"    'progress': {{\n"
                        f"      'overall_percent': deployment.progress_percent  # CORRECT\n"
                        f"    }}\n"
                        f"  }}"
                    )

            # End of payload dict
            if payload_level == 0:
                in_payload_dict = False


def test_no_flat_current_stage_field():
    """Event should NOT have flat 'current_stage' field"""
    method_code = _read_emit_event_method()

    assert method_code is not None

    lines = method_code.split('\n')
    in_payload_dict = False
    payload_level = 0

    for line in lines:
        if 'payload = {' in line:
            in_payload_dict = True
            payload_level = line.count('{') - line.count('}')
            continue

        if in_payload_dict:
            payload_level += line.count('{') - line.count('}')

            if payload_level == 1:
                if "'current_stage':" in line or '"current_stage":' in line:
                    assert False, (
                        f"Found flat 'current_stage' field at line: {line.strip()}\n\n"
                        f"WRONG: 'current_stage' should NOT be at top level of payload.\n"
                        f"CORRECT: Use nested 'progress.stage' instead.\n\n"
                        f"Replace:\n"
                        f"  'current_stage': deployment.current_stage,  # WRONG\n\n"
                        f"With:\n"
                        f"  'progress': {{\n"
                        f"    'stage': deployment.current_stage  # CORRECT\n"
                        f"  }}"
                    )

            if payload_level == 0:
                in_payload_dict = False


# ========== Test 4: Required Top-Level Fields ==========

def test_event_has_type_field():
    """Event must have 'type' field"""
    method_code = _read_emit_event_method()
    assert method_code is not None
    assert "'type':" in method_code or '"type":' in method_code


def test_event_has_deployment_id_field():
    """Event must have 'deployment_id' field"""
    method_code = _read_emit_event_method()
    assert method_code is not None
    assert "'deployment_id':" in method_code or '"deployment_id":' in method_code


def test_event_has_host_id_field():
    """Event must have 'host_id' field"""
    method_code = _read_emit_event_method()
    assert method_code is not None
    assert "'host_id':" in method_code or '"host_id":' in method_code


def test_event_has_status_field():
    """Event must have 'status' field"""
    method_code = _read_emit_event_method()
    assert method_code is not None
    assert "'status':" in method_code or '"status":' in method_code


# ========== Test Summary ==========
#
# Phase 3.4 TDD Tests (Static Code Analysis):
# ✅ test_event_payload_uses_nested_progress_object - Verifies nested structure
# ✅ test_progress_object_contains_overall_percent - Verifies overall_percent field
# ✅ test_progress_object_contains_stage - Verifies stage field
# ✅ test_progress_object_contains_stage_percent - Verifies stage_percent field
# ✅ test_no_flat_progress_percent_field - Rejects flat progress_percent
# ✅ test_no_flat_current_stage_field - Rejects flat current_stage
# ✅ test_event_has_type_field - Verifies type field present
# ✅ test_event_has_deployment_id_field - Verifies deployment_id field present
# ✅ test_event_has_host_id_field - Verifies host_id field present
# ✅ test_event_has_status_field - Verifies status field present
#
# Total: 10 tests
#
# These tests will initially FAIL (RED phase) because:
# 1. _emit_deployment_event() uses flat structure (progress_percent, current_stage)
# 2. No nested 'progress' object
# 3. No stage_percent field
#
# After implementation (GREEN phase):
# - Update _emit_deployment_event() to use nested 'progress' object
# - Add stage_percent field to Deployment model (or use getattr with default)
# - All tests will pass
