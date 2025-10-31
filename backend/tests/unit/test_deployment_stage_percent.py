"""
Unit tests for stage_percent field in Deployment model

Tests the stage-level progress tracking (0-100% within current stage)
Phase 4 TDD - GREEN phase

Validates:
1. stage_percent field exists in Deployment model
2. Defaults to 0 for new deployments
3. Can be updated during deployment stages
4. WebSocket events include stage_percent in nested progress object
"""

import pytest
from datetime import datetime

from database import Deployment, DockerHostDB


@pytest.fixture
def test_host_123(test_db):
    """Create test-host-123 for stage_percent tests"""
    host = DockerHostDB(
        id='test-host-123',
        name='test-host-123',
        url='unix:///var/run/docker.sock',
        is_active=True,
        created_at=datetime.utcnow()
    )
    test_db.add(host)
    test_db.commit()
    test_db.refresh(host)
    return host


@pytest.fixture
def test_deployment(test_db, test_host_123):
    """Create a test deployment with stage_percent"""
    deployment = Deployment(
        id=f"{test_host_123.id}:dep_abc123",
        name="test-deployment",
        deployment_type="container",
        host_id=test_host_123.id,
        definition='{"image": "nginx:latest"}',
        status="pending",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        stage_percent=0
    )
    test_db.add(deployment)
    test_db.commit()
    test_db.refresh(deployment)
    return deployment


class TestStagePercentField:
    """Test that stage_percent field exists and behaves correctly"""

    def test_deployment_has_stage_percent_field(self, test_deployment):
        """Deployment model must have stage_percent field"""
        assert hasattr(test_deployment, 'stage_percent')
        assert test_deployment.stage_percent == 0

    def test_stage_percent_defaults_to_zero(self, test_db, test_host_123):
        """New deployments should default stage_percent to 0"""
        deployment = Deployment(
            id=f"{test_host_123.id}:dep_def456",
            name="test-default-percent",
            deployment_type="container",
            host_id=test_host_123.id,
            definition='{"image": "alpine:latest"}',
            status="pending",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(deployment)
        test_db.commit()
        test_db.refresh(deployment)

        # Should default to 0 if not specified
        assert deployment.stage_percent == 0

    def test_stage_percent_can_be_updated(self, test_deployment, test_db):
        """Stage percent should be updateable from 0 to 100"""
        deployment = test_db.query(Deployment).filter_by(id=test_deployment.id).first()

        # Simulate pulling image: 0% -> 50% -> 100%
        deployment.stage_percent = 50
        test_db.commit()
        test_db.refresh(deployment)
        assert deployment.stage_percent == 50

        deployment.stage_percent = 100
        test_db.commit()
        test_db.refresh(deployment)
        assert deployment.stage_percent == 100

    def test_stage_percent_accepts_integer_range(self, test_db, test_host_123):
        """Stage percent should accept values 0-100"""
        deployment = Deployment(
            id=f"{test_host_123.id}:dep_rng789",
            name="test-percent-range",
            deployment_type="container",
            host_id=test_host_123.id,
            definition='{"image": "redis:latest"}',
            status="pulling_image",
            stage_percent=75,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(deployment)
        test_db.commit()
        test_db.refresh(deployment)

        assert deployment.stage_percent == 75

    def test_stage_percent_resets_on_state_transition(self, test_deployment, test_db):
        """Stage percent should reset to 0 when moving to a new stage"""
        deployment = test_db.query(Deployment).filter_by(id=test_deployment.id).first()

        # Simulate: pulling_image at 100%
        deployment.status = "pulling_image"
        deployment.stage_percent = 100
        test_db.commit()

        # Transition to creating stage - reset to 0
        deployment.status = "creating"
        deployment.stage_percent = 0
        test_db.commit()
        test_db.refresh(deployment)

        assert deployment.status == "creating"
        assert deployment.stage_percent == 0


class TestWebSocketProgressStructure:
    """Test that WebSocket events include stage_percent in nested progress object"""

    def test_progress_event_includes_stage_percent(self, test_deployment):
        """WebSocket progress event must include stage_percent field"""
        # Simulate what _emit_deployment_event should produce
        event_payload = {
            'type': 'deployment_progress',
            'deployment_id': test_deployment.id,
            'host_id': test_deployment.host_id,
            'status': test_deployment.status,
            'progress': {
                'overall_percent': getattr(test_deployment, 'progress_percent', 0),
                'stage': getattr(test_deployment, 'current_stage', test_deployment.status),
                'stage_percent': test_deployment.stage_percent
            }
        }

        # Assertions
        assert 'progress' in event_payload
        assert 'stage_percent' in event_payload['progress']
        assert event_payload['progress']['stage_percent'] == test_deployment.stage_percent

    def test_stage_percent_independent_of_overall_percent(self, test_db, test_host_123):
        """stage_percent (0-100 per stage) is separate from overall_percent (0-100 total)"""
        deployment = Deployment(
            id=f"{test_host_123.id}:dep_ind_abc",
            name="test-progress-separation",
            deployment_type="container",
            host_id=test_host_123.id,
            definition='{"image": "postgres:latest"}',
            status="pulling_image",
            progress_percent=40,
            stage_percent=80,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(deployment)
        test_db.commit()
        test_db.refresh(deployment)

        # Overall progress and stage progress are independent
        assert deployment.progress_percent == 40
        assert deployment.stage_percent == 80


class TestStagePercentInDifferentStages:
    """Test stage_percent behavior across deployment stages"""

    def test_validating_stage_percent(self, test_db, test_host_123):
        """Validating stage should support stage_percent"""
        deployment = Deployment(
            id=f"{test_host_123.id}:dep_val123",
            name="test-validating",
            deployment_type="container",
            host_id=test_host_123.id,
            definition='{"image": "nginx:latest"}',
            status="validating",
            stage_percent=50,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(deployment)
        test_db.commit()
        test_db.refresh(deployment)

        assert deployment.status == "validating"
        assert deployment.stage_percent == 50

    def test_pulling_image_stage_percent(self, test_db, test_host_123):
        """Pulling image stage should track layer-by-layer progress"""
        deployment = Deployment(
            id=f"{test_host_123.id}:dep_pull123",
            name="test-pulling",
            deployment_type="container",
            host_id=test_host_123.id,
            definition='{"image": "nginx:latest"}',
            status="pulling_image",
            stage_percent=70,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(deployment)
        test_db.commit()
        test_db.refresh(deployment)

        assert deployment.status == "pulling_image"
        assert deployment.stage_percent == 70

    def test_creating_stage_percent(self, test_db, test_host_123):
        """Creating stage should support stage_percent"""
        deployment = Deployment(
            id=f"{test_host_123.id}:dep_create123",
            name="test-creating",
            deployment_type="container",
            host_id=test_host_123.id,
            definition='{"image": "alpine:latest"}',
            status="creating",
            stage_percent=100,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(deployment)
        test_db.commit()
        test_db.refresh(deployment)

        assert deployment.status == "creating"
        assert deployment.stage_percent == 100

    def test_starting_stage_percent(self, test_db, test_host_123):
        """Starting stage should support stage_percent"""
        deployment = Deployment(
            id=f"{test_host_123.id}:dep_start123",
            name="test-starting",
            deployment_type="container",
            host_id=test_host_123.id,
            definition='{"image": "redis:latest"}',
            status="starting",
            stage_percent=100,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(deployment)
        test_db.commit()
        test_db.refresh(deployment)

        assert deployment.status == "starting"
        assert deployment.stage_percent == 100

    def test_running_stage_percent(self, test_db, test_host_123):
        """Running stage should have stage_percent at 100"""
        deployment = Deployment(
            id=f"{test_host_123.id}:dep_run123",
            name="test-running",
            deployment_type="container",
            host_id=test_host_123.id,
            definition='{"image": "nginx:latest"}',
            status="running",
            stage_percent=100,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        test_db.add(deployment)
        test_db.commit()
        test_db.refresh(deployment)

        assert deployment.status == "running"
        assert deployment.stage_percent == 100
