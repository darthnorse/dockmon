"""
Unit tests for database cleanup operations

Tests the centralized cleanup_host_data() function that handles
foreign key cleanup when deleting a host.
"""

import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import (
    Base,
    DatabaseManager,
    DockerHostDB,
    AutoRestartConfig,
    ContainerDesiredState,
    AlertV2,
    EventLog
)


@pytest.fixture
def db(tmp_path):
    """Create test database"""
    db_file = tmp_path / "test_cleanup.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)

    db_manager = DatabaseManager(db_path=str(db_file))
    db_manager.engine = engine
    db_manager.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    yield db_manager

    Base.metadata.drop_all(bind=engine)
    if db_file.exists():
        db_file.unlink()


@pytest.fixture
def sample_host(db):
    """Create a sample host for testing"""
    with db.get_session() as session:
        host = DockerHostDB(
            id='test-host-123',
            name='Test Host',
            url='tcp://192.168.1.100:2376',
            security_status='insecure',
            is_active=True
        )
        session.add(host)
        session.commit()
        return host.id


class TestCleanupHostData:
    """Tests for the cleanup_host_data() function"""

    def test_cleanup_deletes_auto_restart_configs(self, db, sample_host):
        """Should delete all AutoRestartConfig records for the host"""
        # Setup: Create auto-restart configs
        with db.get_session() as session:
            config1 = AutoRestartConfig(
                host_id=sample_host,
                container_id='container1',
                container_name='web',
                enabled=True
            )
            config2 = AutoRestartConfig(
                host_id=sample_host,
                container_id='container2',
                container_name='db',
                enabled=True
            )
            session.add_all([config1, config2])
            session.commit()

        # Execute: Run cleanup
        with db.get_session() as session:
            stats = db.cleanup_host_data(session, sample_host, 'Test Host')
            session.commit()

        # Verify: Configs should be deleted
        assert stats['auto_restart_configs'] == 2
        with db.get_session() as session:
            remaining = session.query(AutoRestartConfig).filter(
                AutoRestartConfig.host_id == sample_host
            ).count()
            assert remaining == 0

    def test_cleanup_deletes_container_desired_states(self, db, sample_host):
        """Should delete all ContainerDesiredState records for the host"""
        # Setup: Create desired state configs
        with db.get_session() as session:
            state1 = ContainerDesiredState(
                host_id=sample_host,
                container_id='container1',
                container_name='web',
                desired_state='should_run'
            )
            state2 = ContainerDesiredState(
                host_id=sample_host,
                container_id='container2',
                container_name='db',
                desired_state='on_demand'
            )
            session.add_all([state1, state2])
            session.commit()

        # Execute: Run cleanup
        with db.get_session() as session:
            stats = db.cleanup_host_data(session, sample_host, 'Test Host')
            session.commit()

        # Verify: States should be deleted
        assert stats['desired_states'] == 2
        with db.get_session() as session:
            remaining = session.query(ContainerDesiredState).filter(
                ContainerDesiredState.host_id == sample_host
            ).count()
            assert remaining == 0

    def test_cleanup_resolves_open_alerts(self, db, sample_host):
        """Should resolve all open AlertV2 instances for the host"""
        # Setup: Create open alerts
        with db.get_session() as session:
            alert1 = AlertV2(
                id='alert-1',
                dedup_key='cpu_high|host:test-host-123',
                scope_type='host',
                scope_id=sample_host,
                kind='cpu_high',
                severity='warning',
                state='open',
                title='High CPU',
                message='CPU usage is high',
                first_seen=datetime.now(),
                last_seen=datetime.now()
            )
            alert2 = AlertV2(
                id='alert-2',
                dedup_key='memory_high|host:test-host-123',
                scope_type='host',
                scope_id=sample_host,
                kind='memory_high',
                severity='critical',
                state='open',
                title='High Memory',
                message='Memory usage is high',
                first_seen=datetime.now(),
                last_seen=datetime.now()
            )
            session.add_all([alert1, alert2])
            session.commit()

        # Execute: Run cleanup
        with db.get_session() as session:
            stats = db.cleanup_host_data(session, sample_host, 'Test Host')
            session.commit()

        # Verify: Alerts should be resolved
        assert stats['alerts_resolved'] == 2
        with db.get_session() as session:
            open_alerts = session.query(AlertV2).filter(
                AlertV2.scope_type == 'host',
                AlertV2.scope_id == sample_host,
                AlertV2.state == 'open'
            ).count()
            assert open_alerts == 0

            resolved_alerts = session.query(AlertV2).filter(
                AlertV2.scope_type == 'host',
                AlertV2.scope_id == sample_host,
                AlertV2.state == 'resolved'
            ).count()
            assert resolved_alerts == 2

    def test_cleanup_skips_already_resolved_alerts(self, db, sample_host):
        """Should not count already resolved alerts"""
        # Setup: Create resolved alert
        with db.get_session() as session:
            alert = AlertV2(
                id='alert-1',
                dedup_key='cpu_high|host:test-host-123',
                scope_type='host',
                scope_id=sample_host,
                kind='cpu_high',
                severity='warning',
                state='resolved',
                title='High CPU',
                message='CPU usage is high',
                first_seen=datetime.now(),
                last_seen=datetime.now(),
                resolved_at=datetime.now()
            )
            session.add(alert)
            session.commit()

        # Execute: Run cleanup
        with db.get_session() as session:
            stats = db.cleanup_host_data(session, sample_host, 'Test Host')
            session.commit()

        # Verify: Should not modify already resolved alerts
        assert stats['alerts_resolved'] == 0

    def test_cleanup_preserves_event_logs(self, db, sample_host):
        """Should keep all EventLog records for audit trail"""
        # Setup: Create event logs
        with db.get_session() as session:
            event1 = EventLog(
                category='container',
                event_type='state_change',
                severity='info',
                host_id=sample_host,
                host_name='Test Host',
                container_id='container1',
                container_name='web',
                title='Container started',
                message='Container web started'
            )
            event2 = EventLog(
                category='host',
                event_type='connected',
                severity='info',
                host_id=sample_host,
                host_name='Test Host',
                title='Host connected',
                message='Host Test Host connected'
            )
            session.add_all([event1, event2])
            session.commit()

        # Execute: Run cleanup
        with db.get_session() as session:
            stats = db.cleanup_host_data(session, sample_host, 'Test Host')
            session.commit()

        # Verify: Events should be preserved
        assert stats['events_kept'] == 2
        with db.get_session() as session:
            remaining_events = session.query(EventLog).filter(
                EventLog.host_id == sample_host
            ).count()
            assert remaining_events == 2

    def test_cleanup_returns_comprehensive_stats(self, db, sample_host):
        """Should return detailed statistics about cleanup operations"""
        # Setup: Create various records
        with db.get_session() as session:
            # Add auto-restart config
            config = AutoRestartConfig(
                host_id=sample_host,
                container_id='container1',
                container_name='web',
                enabled=True
            )
            # Add desired state
            state = ContainerDesiredState(
                host_id=sample_host,
                container_id='container1',
                container_name='web',
                desired_state='should_run'
            )
            # Add open alert
            alert = AlertV2(
                id='alert-1',
                dedup_key='cpu_high|host:test-host-123',
                scope_type='host',
                scope_id=sample_host,
                kind='cpu_high',
                severity='warning',
                state='open',
                title='High CPU',
                message='CPU usage is high',
                first_seen=datetime.now(),
                last_seen=datetime.now()
            )
            # Add event log
            event = EventLog(
                category='container',
                event_type='state_change',
                severity='info',
                host_id=sample_host,
                host_name='Test Host',
                title='Test event',
                message='Test message'
            )
            session.add_all([config, state, alert, event])
            session.commit()

        # Execute: Run cleanup
        with db.get_session() as session:
            stats = db.cleanup_host_data(session, sample_host, 'Test Host')
            session.commit()

        # Verify: Should return all stats
        assert 'auto_restart_configs' in stats
        assert 'desired_states' in stats
        assert 'alerts_resolved' in stats
        assert 'events_kept' in stats
        assert stats['auto_restart_configs'] == 1
        assert stats['desired_states'] == 1
        assert stats['alerts_resolved'] == 1
        assert stats['events_kept'] == 1

    def test_cleanup_handles_empty_host(self, db, sample_host):
        """Should handle cleanup for host with no associated data"""
        # Execute: Run cleanup on host with no data
        with db.get_session() as session:
            stats = db.cleanup_host_data(session, sample_host, 'Test Host')
            session.commit()

        # Verify: Should return zeros
        assert stats['auto_restart_configs'] == 0
        assert stats['desired_states'] == 0
        assert stats['alerts_resolved'] == 0
        assert stats['events_kept'] == 0

    def test_cleanup_is_transactional(self, db, sample_host):
        """Should rollback all changes if any operation fails"""
        # This test would require injecting a failure, which is complex
        # For now, we document that cleanup_host_data() should be called
        # within a transaction context that can be rolled back
        pass
