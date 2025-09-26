"""
Tests for Docker event processing and handling
Ensures all Docker events are properly processed and trigger appropriate actions
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime
import json


class TestDockerEventProcessing:
    """Test Docker event handling"""

    def test_parse_docker_event(self):
        """Test parsing raw Docker events"""
        from docker_monitor.event_processor import parse_docker_event

        raw_event = {
            "Type": "container",
            "Action": "die",
            "Actor": {
                "ID": "abc123def456",
                "Attributes": {
                    "exitCode": "1",
                    "image": "nginx:latest",
                    "name": "web-server"
                }
            },
            "time": 1234567890
        }

        parsed = parse_docker_event(raw_event)

        assert parsed["type"] == "container"
        assert parsed["action"] == "die"
        assert parsed["container_id"] == "abc123def456"
        assert parsed["exit_code"] == 1
        assert parsed["container_name"] == "web-server"

    def test_health_check_event_processing(self):
        """Test health check status change events"""
        from docker_monitor.event_processor import process_health_event

        # Healthy -> Unhealthy transition
        event = {
            "Type": "container",
            "Action": "health_status: unhealthy",
            "Actor": {
                "ID": "container123",
                "Attributes": {"name": "database"}
            }
        }

        result = process_health_event(event)
        assert result["should_alert"] is True
        assert result["severity"] == "high"
        assert result["health_status"] == "unhealthy"

        # Unhealthy -> Healthy recovery
        event["Action"] = "health_status: healthy"
        result = process_health_event(event)
        assert result["should_alert"] is False  # Info only
        assert result["health_status"] == "healthy"

    def test_oom_event_detection(self):
        """Test Out of Memory event detection"""
        from docker_monitor.event_processor import is_oom_event

        # OOM kill event
        event1 = {
            "Type": "container",
            "Action": "die",
            "Actor": {
                "Attributes": {"exitCode": "137"}  # SIGKILL from OOM
            }
        }
        assert is_oom_event(event1) is True

        # Explicit OOM event
        event2 = {
            "Type": "container",
            "Action": "oom"
        }
        assert is_oom_event(event2) is True

        # Normal exit
        event3 = {
            "Type": "container",
            "Action": "die",
            "Actor": {
                "Attributes": {"exitCode": "0"}
            }
        }
        assert is_oom_event(event3) is False

    def test_restart_loop_detection_from_events(self):
        """Test detection of restart loops from event stream"""
        from docker_monitor.event_processor import RestartLoopDetector

        detector = RestartLoopDetector()

        container_id = "abc123"

        # Simulate restart events
        for i in range(4):
            event = {
                "Type": "container",
                "Action": "restart",
                "Actor": {"ID": container_id},
                "time": datetime.utcnow().timestamp() + i * 30  # 30 seconds apart
            }
            detector.add_event(event)

        # Should detect restart loop (4 restarts in 2 minutes)
        assert detector.is_restart_loop(container_id, threshold=3, window_minutes=5) is True

    def test_event_filtering(self):
        """Test filtering of events we care about"""
        from docker_monitor.event_processor import should_process_event

        # Events we care about
        important_events = [
            {"Type": "container", "Action": "start"},
            {"Type": "container", "Action": "stop"},
            {"Type": "container", "Action": "die"},
            {"Type": "container", "Action": "oom"},
            {"Type": "container", "Action": "health_status: unhealthy"},
            {"Type": "container", "Action": "kill"},
            {"Type": "container", "Action": "pause"},
            {"Type": "container", "Action": "unpause"}
        ]

        for event in important_events:
            assert should_process_event(event) is True

        # Events we ignore
        ignored_events = [
            {"Type": "network", "Action": "connect"},
            {"Type": "volume", "Action": "mount"},
            {"Type": "image", "Action": "pull"},
            {"Type": "container", "Action": "exec_start"},
            {"Type": "container", "Action": "exec_die"}
        ]

        for event in ignored_events:
            assert should_process_event(event) is False

    def test_event_to_alert_mapping(self):
        """Test mapping Docker events to alert rules"""
        from docker_monitor.event_processor import should_trigger_alert

        alert_rule = {
            "trigger_events": ["die", "oom", "health_status:unhealthy"]
        }

        # Should trigger
        trigger_events = [
            {"Action": "die"},
            {"Action": "oom"},
            {"Action": "health_status: unhealthy"}
        ]

        for event in trigger_events:
            assert should_trigger_alert(event, alert_rule) is True

        # Should not trigger
        no_trigger_events = [
            {"Action": "start"},
            {"Action": "stop"},
            {"Action": "health_status: healthy"}
        ]

        for event in no_trigger_events:
            assert should_trigger_alert(event, alert_rule) is False

    @patch('docker_monitor.monitor.DockerMonitor')
    async def test_event_stream_monitoring(self, mock_monitor):
        """Test continuous Docker event stream monitoring"""
        from docker_monitor.event_processor import EventStreamMonitor

        mock_client = MagicMock()
        mock_events = [
            {"Type": "container", "Action": "start", "Actor": {"ID": "abc123"}},
            {"Type": "container", "Action": "die", "Actor": {"ID": "abc123", "Attributes": {"exitCode": "1"}}}
        ]
        mock_client.events.return_value = iter(mock_events)

        monitor = EventStreamMonitor(mock_client, "host123")
        processed_events = []

        async def event_handler(event):
            processed_events.append(event)

        monitor.on_event = event_handler

        # Process events
        await monitor.start()

        # Should process both events
        assert len(processed_events) == 2
        assert processed_events[0]["Action"] == "start"
        assert processed_events[1]["Action"] == "die"

    def test_event_enrichment(self):
        """Test enriching events with additional context"""
        from docker_monitor.event_processor import enrich_event

        raw_event = {
            "Type": "container",
            "Action": "die",
            "Actor": {
                "ID": "abc123",
                "Attributes": {
                    "exitCode": "1",
                    "name": "web-app"
                }
            }
        }

        enriched = enrich_event(raw_event, host_id="host123")

        assert enriched["host_id"] == "host123"
        assert enriched["timestamp"] is not None
        assert enriched["severity"] is not None
        assert enriched["container_short_id"] == "abc123"[:12]

    def test_network_event_handling(self):
        """Test handling of network-related Docker events"""
        from docker_monitor.event_processor import process_network_event

        # Network disconnect
        event = {
            "Type": "network",
            "Action": "disconnect",
            "Actor": {
                "Attributes": {
                    "container": "abc123",
                    "name": "bridge"
                }
            }
        }

        result = process_network_event(event)
        assert result["event_type"] == "network_disconnect"
        assert result["container_id"] == "abc123"

    def test_volume_event_handling(self):
        """Test handling of volume-related Docker events"""
        from docker_monitor.event_processor import process_volume_event

        # Volume unmount
        event = {
            "Type": "volume",
            "Action": "unmount",
            "Actor": {
                "ID": "volume123",
                "Attributes": {
                    "container": "abc123"
                }
            }
        }

        result = process_volume_event(event)
        assert result is not None  # We track but don't alert on volume events

    def test_exec_event_filtering(self):
        """Test filtering of exec events (usually noise)"""
        from docker_monitor.event_processor import should_track_exec

        # Exec into container - usually debugging, don't track
        event = {
            "Type": "container",
            "Action": "exec_start",
            "Actor": {
                "Attributes": {
                    "execID": "exec123"
                }
            }
        }

        assert should_track_exec(event) is False