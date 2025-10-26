"""
Tests for EventBus system.

Critical for v2.1 because:
- v2.1 adds deployment event types
- Must verify events use composite keys
- Must verify event structure supports host and container events
"""

import pytest
from datetime import datetime

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from event_bus import Event, EventType


@pytest.mark.unit
def test_event_creation():
    """
    Test that events can be created with required fields.
    """
    event = Event(
        event_type=EventType.CONTAINER_STARTED,
        scope_type='container',
        scope_id='7be442c9-24bc-4047-b33a-41bbf51ea2f9:abc123',  # Composite key
        scope_name='test-nginx',
        host_id='7be442c9-24bc-4047-b33a-41bbf51ea2f9',
        host_name='test-host',
        data={'message': 'Container started'}
    )

    assert event.event_type == EventType.CONTAINER_STARTED
    assert event.scope_id == '7be442c9-24bc-4047-b33a-41bbf51ea2f9:abc123'
    assert ':' in event.scope_id  # Composite key


@pytest.mark.unit
def test_event_uses_composite_key_for_container_id():
    """
    Test that events use composite key format for scope_id (container events).

    Critical: Multi-host support requires {host_id}:{container_id} format.
    """
    event = Event(
        event_type=EventType.CONTAINER_STOPPED,
        scope_type='container',
        scope_id='7be442c9-24bc-4047-b33a-41bbf51ea2f9:abc123def456',  # Composite
        scope_name='my-container',
        host_id='7be442c9-24bc-4047-b33a-41bbf51ea2f9',
        data={'reason': 'user requested'}
    )

    # Verify composite key format
    assert ':' in event.scope_id
    parts = event.scope_id.split(':', 1)
    assert len(parts) == 2
    assert len(parts[0]) == 36  # UUID
    assert len(parts[1]) == 12  # SHORT ID


@pytest.mark.unit
def test_event_without_container_id_is_valid():
    """
    Test that events can be created for host-level events.

    Critical for v2.1: Some events are host-level, not container-level.
    """
    event = Event(
        event_type=EventType.HOST_CONNECTED,
        scope_type='host',
        scope_id='7be442c9-24bc-4047-b33a-41bbf51ea2f9',  # Host ID
        scope_name='production-host',
        data={'timestamp': datetime.utcnow().isoformat()}
    )

    assert event.event_type == EventType.HOST_CONNECTED
    assert event.scope_type == 'host'
    assert event.scope_id == '7be442c9-24bc-4047-b33a-41bbf51ea2f9'


@pytest.mark.unit
def test_deployment_event_types_structure():
    """
    Test that event structure can handle deployment-related events.

    Critical for v2.1: Deployment events will use this same Event structure.
    """
    # While deployment event types don't exist yet in EventType enum,
    # the Event class can handle any event_type string
    
    # Test with existing event types to validate structure
    event_types_to_test = [
        EventType.UPDATE_STARTED,
        EventType.UPDATE_COMPLETED,
        EventType.UPDATE_FAILED,
        EventType.CONTAINER_STARTED,
    ]

    for event_type in event_types_to_test:
        event = Event(
            event_type=event_type,
            scope_type='container',
            scope_id='test-host:container123',
            scope_name='test-container',
            host_id='test-host',
            data={'deployment_id': 'host:deploy123'}  # v2.1 will add this data
        )

        assert event.event_type == event_type
        assert event.data.get('deployment_id') == 'host:deploy123'


@pytest.mark.unit
def test_event_bus_instance_creation(event_bus):
    """
    Test that EventBus can be instantiated with mock monitor.
    """
    assert event_bus is not None
    assert event_bus.monitor is not None


@pytest.mark.unit
def test_event_to_dict_includes_composite_key():
    """
    Test that Event.to_dict() preserves composite key in scope_id.
    """
    event = Event(
        event_type=EventType.UPDATE_AVAILABLE,
        scope_type='container',
        scope_id='7be442c9-24bc-4047-b33a-41bbf51ea2f9:abc123def456',
        scope_name='nginx-prod',
        host_id='7be442c9-24bc-4047-b33a-41bbf51ea2f9',
        host_name='prod-host',
        data={'current': 'nginx:1.24', 'latest': 'nginx:1.25'}
    )

    event_dict = event.to_dict()

    # Verify dict structure
    assert event_dict['event_type'] == 'update_available'
    assert event_dict['scope_type'] == 'container'
    assert event_dict['scope_id'] == '7be442c9-24bc-4047-b33a-41bbf51ea2f9:abc123def456'
    assert ':' in event_dict['scope_id']  # Composite key preserved
    assert event_dict['timestamp'].endswith('Z')  # Timestamp has 'Z' suffix
