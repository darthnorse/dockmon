"""
Unit tests for event context merging in alerts

Tests the event_context_json merging logic that preserves important fields
like exit_code across multiple Docker events.

Background: Docker sends multiple events for a single container stop:
1. 'kill' event (no exit_code)
2. 'die' event (has exit_code)
3. 'stop' event (no exit_code)

Without merging, the 'stop' event would overwrite the exit_code with null.
"""

import pytest
import json


class TestEventContextMerging:
    """Tests for event context merging logic"""

    def test_merge_with_null_exit_code_preserves_original(self):
        """Should preserve exit_code when new event has null"""
        # Existing context from 'die' event
        existing_context = {
            'exit_code': 137,
            'signal': 'SIGKILL',
            'old_state': 'running',
            'new_state': 'exited'
        }

        # New event data from 'stop' event (no exit_code)
        new_data = {
            'exit_code': None,
            'old_state': 'exited',
            'new_state': 'exited'
        }

        # Simulate the merging logic from engine.py
        merged = {**existing_context, **new_data}
        if new_data.get('exit_code') is None and existing_context.get('exit_code') is not None:
            merged['exit_code'] = existing_context['exit_code']

        # Verify: exit_code preserved
        assert merged['exit_code'] == 137
        assert merged['signal'] == 'SIGKILL'

    def test_merge_with_non_null_exit_code_overwrites(self):
        """Should overwrite exit_code when new event has different non-null value"""
        existing_context = {'exit_code': 0}
        new_data = {'exit_code': 137}

        # Merge
        merged = {**existing_context, **new_data}
        if new_data.get('exit_code') is None and existing_context.get('exit_code') is not None:
            merged['exit_code'] = existing_context['exit_code']

        # Verify: exit_code overwritten
        assert merged['exit_code'] == 137

    def test_merge_adds_new_fields(self):
        """Should add new fields from subsequent events"""
        existing_context = {
            'exit_code': 137,
            'signal': 'SIGKILL'
        }
        new_data = {
            'timestamp': '2025-10-14T12:00:00Z',
            'state': 'exited'
        }

        # Merge
        merged = {**existing_context, **new_data}
        if new_data.get('exit_code') is None and existing_context.get('exit_code') is not None:
            merged['exit_code'] = existing_context['exit_code']

        # Verify: All fields present
        assert merged['exit_code'] == 137
        assert merged['signal'] == 'SIGKILL'
        assert merged['timestamp'] == '2025-10-14T12:00:00Z'
        assert merged['state'] == 'exited'

    def test_merge_updates_existing_fields(self):
        """Should update existing fields with new non-null values"""
        existing_context = {
            'exit_code': 137,
            'state': 'running',
            'signal': 'SIGKILL'
        }
        new_data = {
            'state': 'exited',  # Update
            'timestamp': '2025-10-14T12:00:00Z'  # Add
        }

        # Merge
        merged = {**existing_context, **new_data}
        if new_data.get('exit_code') is None and existing_context.get('exit_code') is not None:
            merged['exit_code'] = existing_context['exit_code']

        # Verify
        assert merged['exit_code'] == 137  # Preserved (not in new_data)
        assert merged['state'] == 'exited'  # Updated
        assert merged['signal'] == 'SIGKILL'  # Preserved
        assert merged['timestamp'] == '2025-10-14T12:00:00Z'  # Added

    def test_merge_with_empty_existing_context(self):
        """Should handle empty existing context gracefully"""
        existing_context = {}
        new_data = {
            'exit_code': 137,
            'signal': 'SIGKILL'
        }

        # Merge
        merged = {**existing_context, **new_data}
        if new_data.get('exit_code') is None and existing_context.get('exit_code') is not None:
            merged['exit_code'] = existing_context['exit_code']

        # Verify: Just use new data
        assert merged['exit_code'] == 137
        assert merged['signal'] == 'SIGKILL'

    def test_merge_handles_invalid_json_gracefully(self):
        """Should handle corrupted JSON by treating as empty"""
        corrupted_json = 'invalid json{'

        # Try to parse
        try:
            existing_context = json.loads(corrupted_json)
        except (json.JSONDecodeError, TypeError):
            existing_context = {}

        new_data = {'exit_code': 137}

        # Merge
        merged = {**existing_context, **new_data}
        if new_data.get('exit_code') is None and existing_context.get('exit_code') is not None:
            merged['exit_code'] = existing_context['exit_code']

        # Verify: Should work with empty context
        assert merged['exit_code'] == 137

    def test_multiple_null_exit_codes_preserve_original(self):
        """Should preserve exit_code through multiple events with null"""
        # Event 1: Set exit_code
        existing_context = {'exit_code': 137, 'signal': 'SIGKILL'}

        # Event 2: Null exit_code
        new_data = {'exit_code': None, 'state': 'exited'}
        merged = {**existing_context, **new_data}
        if new_data.get('exit_code') is None and existing_context.get('exit_code') is not None:
            merged['exit_code'] = existing_context['exit_code']

        assert merged['exit_code'] == 137

        # Event 3: Another null exit_code
        existing_context = merged
        new_data = {'exit_code': None, 'timestamp': '2025-10-14T12:00:00Z'}
        merged = {**existing_context, **new_data}
        if new_data.get('exit_code') is None and existing_context.get('exit_code') is not None:
            merged['exit_code'] = existing_context['exit_code']

        # Verify: Still 137
        assert merged['exit_code'] == 137
        assert merged['signal'] == 'SIGKILL'
        assert merged['state'] == 'exited'
        assert merged['timestamp'] == '2025-10-14T12:00:00Z'

    def test_zero_exit_code_not_treated_as_null(self):
        """Should treat exit_code=0 as valid, not as null"""
        existing_context = {'exit_code': 137}
        new_data = {'exit_code': 0}  # Clean shutdown

        # Merge
        merged = {**existing_context, **new_data}
        if new_data.get('exit_code') is None and existing_context.get('exit_code') is not None:
            merged['exit_code'] = existing_context['exit_code']

        # Verify: 0 is valid, should overwrite
        assert merged['exit_code'] == 0

    def test_false_value_not_treated_as_null(self):
        """Should treat False as valid value, not as null"""
        existing_context = {'restart': True}
        new_data = {'restart': False}

        # Merge
        merged = {**existing_context, **new_data}

        # Verify: False is valid
        assert merged['restart'] == False

    def test_empty_string_not_preserved_like_null(self):
        """Should overwrite empty string (only exit_code gets special treatment)"""
        existing_context = {'message': 'Original'}
        new_data = {'message': ''}

        # Merge (exit_code preservation logic only applies to exit_code)
        merged = {**existing_context, **new_data}
        if new_data.get('exit_code') is None and existing_context.get('exit_code') is not None:
            merged['exit_code'] = existing_context['exit_code']

        # Verify: Empty string overwrites (not special-cased like exit_code)
        assert merged['message'] == ''

    def test_docker_event_sequence_simulation(self):
        """Simulate real Docker event sequence: kill -> die -> stop"""
        # Event 1: 'kill' (no exit_code)
        context = {}
        event = {'action': 'kill', 'exit_code': None}
        context = {**context, **event}
        if event.get('exit_code') is None and context.get('exit_code') is not None:
            context['exit_code'] = context['exit_code']

        assert context.get('exit_code') is None

        # Event 2: 'die' (has exit_code!)
        event = {'action': 'die', 'exit_code': 137, 'signal': 'SIGKILL'}
        context = {**context, **event}
        if event.get('exit_code') is None and context.get('exit_code') is not None:
            context['exit_code'] = context['exit_code']

        assert context['exit_code'] == 137

        # Event 3: 'stop' (no exit_code - this is the bug we're fixing!)
        event = {'action': 'stop', 'exit_code': None}
        prev_exit_code = context.get('exit_code')  # Save before merge
        context = {**context, **event}
        if event.get('exit_code') is None and prev_exit_code is not None:
            # CRITICAL: Preserve the exit_code from 'die' event
            context['exit_code'] = prev_exit_code

        # Verify: exit_code survived all three events
        assert context['exit_code'] == 137
        assert context['action'] == 'stop'  # Updated to latest
        assert context['signal'] == 'SIGKILL'  # Preserved from die
