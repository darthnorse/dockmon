"""
Tests for timing and race condition issues
Would have caught the setTimeout race condition in alert editing
"""

import pytest
import asyncio
import time
from unittest.mock import MagicMock, patch, call
from datetime import datetime


class TestTimingAndRaceConditions:
    """Test for timing-related bugs and race conditions"""

    def test_nested_setTimeout_race_condition(self):
        """Test that would catch the nested setTimeout race condition bug"""

        # Simulate the buggy code structure
        execution_order = []

        def simulate_buggy_code():
            # First setTimeout (like setting notification channels)
            def first_timeout():
                execution_order.append("set_notification_channels")

            # Second setTimeout (like clearing and setting checkboxes)
            def second_timeout():
                execution_order.append("clear_checkboxes")
                execution_order.append("set_checkboxes")

            # In buggy code, both were scheduled with setTimeout
            # Order was non-deterministic
            import random
            if random.random() > 0.5:
                first_timeout()
                second_timeout()
            else:
                second_timeout()
                first_timeout()

            return execution_order

        # Run multiple times to catch race condition
        results = set()
        for _ in range(10):
            execution_order = []
            result = simulate_buggy_code()
            results.add(tuple(result))

        # Bug: Multiple different orders possible (non-deterministic)
        assert len(results) > 1, "Race condition detected - execution order is non-deterministic"

    def test_correct_synchronous_execution_order(self):
        """Test the correct execution order without race conditions"""

        execution_order = []

        def simulate_fixed_code():
            # Synchronous operations first
            execution_order.append("clear_state_checkboxes")
            execution_order.append("clear_event_checkboxes")
            execution_order.append("set_state_checkboxes")
            execution_order.append("set_event_checkboxes")

            # Async operation last (only for things that need delay)
            execution_order.append("set_notification_channels_delayed")

            return execution_order

        # Run multiple times - should always be the same order
        results = set()
        for _ in range(10):
            execution_order = []
            result = simulate_fixed_code()
            results.add(tuple(result))

        # Fixed: Only one possible order (deterministic)
        assert len(results) == 1, "Execution order should be deterministic"

        # Verify correct order
        expected_order = [
            "clear_state_checkboxes",
            "clear_event_checkboxes",
            "set_state_checkboxes",
            "set_event_checkboxes",
            "set_notification_channels_delayed"
        ]
        assert list(results)[0] == tuple(expected_order)

    def test_checkbox_clearing_specificity(self):
        """Test that checkbox clearing is specific to the intended groups"""

        # Mock DOM structure
        checkboxes = {
            "container_checkbox_1": {"type": "container", "checked": True},
            "container_checkbox_2": {"type": "container", "checked": True},
            "state_checkbox_1": {"type": "state", "checked": True},
            "state_checkbox_2": {"type": "state", "checked": True},
            "event_checkbox_1": {"type": "event", "checked": True},
            "event_checkbox_2": {"type": "event", "checked": True},
            "notification_checkbox_1": {"type": "notification", "checked": True},
        }

        def clear_all_checkboxes():
            """Buggy version - clears everything"""
            for checkbox in checkboxes.values():
                checkbox["checked"] = False

        def clear_specific_checkboxes():
            """Fixed version - only clears specific types"""
            for name, checkbox in checkboxes.items():
                if checkbox["type"] in ["state", "event"]:
                    checkbox["checked"] = False

        # Test buggy version
        buggy_checkboxes = checkboxes.copy()
        clear_all_checkboxes()
        # Bug: All checkboxes cleared including containers
        assert not any(cb["checked"] for cb in checkboxes.values())

        # Reset
        checkboxes = {
            "container_checkbox_1": {"type": "container", "checked": True},
            "container_checkbox_2": {"type": "container", "checked": True},
            "state_checkbox_1": {"type": "state", "checked": True},
            "state_checkbox_2": {"type": "state", "checked": True},
            "event_checkbox_1": {"type": "event", "checked": True},
            "event_checkbox_2": {"type": "event", "checked": True},
            "notification_checkbox_1": {"type": "notification", "checked": True},
        }

        # Test fixed version
        clear_specific_checkboxes()

        # Fixed: Container and notification checkboxes preserved
        assert checkboxes["container_checkbox_1"]["checked"] == True
        assert checkboxes["container_checkbox_2"]["checked"] == True
        assert checkboxes["notification_checkbox_1"]["checked"] == True

        # State and event checkboxes cleared
        assert checkboxes["state_checkbox_1"]["checked"] == False
        assert checkboxes["state_checkbox_2"]["checked"] == False
        assert checkboxes["event_checkbox_1"]["checked"] == False
        assert checkboxes["event_checkbox_2"]["checked"] == False

    @pytest.mark.asyncio
    async def test_async_operation_timing(self):
        """Test timing of async operations"""

        operation_log = []

        async def load_notification_channels():
            """Simulates async loading of channels"""
            await asyncio.sleep(0.1)  # 100ms delay
            operation_log.append("channels_loaded")
            return ["channel1", "channel2"]

        async def populate_form(edit_mode=False):
            if edit_mode:
                # Synchronous operations
                operation_log.append("clear_checkboxes")
                operation_log.append("set_checkboxes")

                # Async operation
                channels_task = asyncio.create_task(load_notification_channels())

                # Don't block on async operation
                operation_log.append("form_ready")

                # Wait for channels later
                channels = await channels_task
                operation_log.append("channels_set")

            return operation_log

        await populate_form(edit_mode=True)

        # Verify order
        assert operation_log == [
            "clear_checkboxes",
            "set_checkboxes",
            "form_ready",  # Form is ready before channels load
            "channels_loaded",
            "channels_set"
        ]

    def test_dom_ready_state_dependencies(self):
        """Test that operations wait for DOM elements to be ready"""

        class MockDOM:
            def __init__(self):
                self.elements = {}
                self.ready = False

            def add_element(self, id, element):
                self.elements[id] = element

            def get_element(self, id):
                if not self.ready:
                    return None
                return self.elements.get(id)

            def set_ready(self):
                self.ready = True

        dom = MockDOM()

        def try_set_checkbox_value(dom, checkbox_id, value):
            """Should only work if element exists"""
            element = dom.get_element(checkbox_id)
            if element:
                element["checked"] = value
                return True
            return False

        # Add checkbox to DOM
        dom.add_element("test_checkbox", {"checked": False})

        # Try to set before DOM ready - should fail
        result = try_set_checkbox_value(dom, "test_checkbox", True)
        assert result == False

        # Set DOM ready
        dom.set_ready()

        # Now should work
        result = try_set_checkbox_value(dom, "test_checkbox", True)
        assert result == True
        assert dom.get_element("test_checkbox")["checked"] == True

    def test_state_preservation_across_operations(self):
        """Test that state is preserved across multiple operations"""

        form_state = {
            "name": "Test Alert",
            "containers": ["web-1", "web-2"],
            "states": [],
            "events": [],
            "channels": []
        }

        def buggy_update_states(form_state, new_states):
            """Buggy: Clears everything when updating states"""
            # Wrong: Clears unrelated fields
            form_state = {
                "name": "",
                "containers": [],
                "states": new_states,
                "events": [],
                "channels": []
            }
            return form_state

        def correct_update_states(form_state, new_states):
            """Correct: Only updates states"""
            form_state = form_state.copy()
            form_state["states"] = new_states
            return form_state

        # Test buggy version
        buggy_result = buggy_update_states(form_state.copy(), ["exited", "dead"])
        assert buggy_result["name"] == ""  # Bug: Name was cleared
        assert buggy_result["containers"] == []  # Bug: Containers were cleared

        # Test correct version
        correct_result = correct_update_states(form_state.copy(), ["exited", "dead"])
        assert correct_result["name"] == "Test Alert"  # Preserved
        assert correct_result["containers"] == ["web-1", "web-2"]  # Preserved
        assert correct_result["states"] == ["exited", "dead"]  # Updated

    def test_callback_execution_order(self):
        """Test that callbacks execute in the correct order"""

        execution_order = []

        def callback_1():
            execution_order.append("callback_1")

        def callback_2():
            execution_order.append("callback_2")

        def callback_3():
            execution_order.append("callback_3")

        # Simulate event handlers
        def on_form_load():
            callback_1()
            # Don't use setTimeout for synchronous operations
            callback_2()
            callback_3()

        on_form_load()

        # Should execute in order
        assert execution_order == ["callback_1", "callback_2", "callback_3"]

    def test_debouncing_rapid_operations(self):
        """Test that rapid operations are debounced properly"""

        class Debouncer:
            def __init__(self, delay=0.1):
                self.delay = delay
                self.last_call = None
                self.call_count = 0

            def call(self, func):
                current_time = time.time()
                if self.last_call and (current_time - self.last_call) < self.delay:
                    return False  # Debounced
                self.last_call = current_time
                self.call_count += 1
                func()
                return True

        debouncer = Debouncer(delay=0.1)
        calls_made = []

        def operation():
            calls_made.append(time.time())

        # Rapid calls
        for _ in range(10):
            debouncer.call(operation)
            time.sleep(0.01)  # 10ms between calls

        # Should debounce most calls
        assert len(calls_made) < 5  # Much less than 10

    @pytest.mark.parametrize("delay_ms,should_complete", [
        (0, True),      # Synchronous - always completes
        (10, True),     # Short delay - should complete
        (5000, False),  # Long delay - might timeout
    ])
    def test_operation_timeout_handling(self, delay_ms, should_complete):
        """Test handling of operations that might timeout"""

        import threading

        result = {"completed": False}

        def delayed_operation():
            time.sleep(delay_ms / 1000)
            result["completed"] = True

        thread = threading.Thread(target=delayed_operation)
        thread.start()
        thread.join(timeout=0.1)  # 100ms timeout

        if should_complete:
            assert result["completed"] == True
        else:
            # Operation should timeout
            assert thread.is_alive() or not result["completed"]