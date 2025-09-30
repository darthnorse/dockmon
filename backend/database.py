"""
Database models and operations for DockMon
Uses SQLite for persistent storage of configuration and settings
"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy import create_engine, Column, String, Integer, Boolean, DateTime, JSON, ForeignKey, Text, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from sqlalchemy.pool import StaticPool
import json
import os
import logging
import secrets
import bcrypt

logger = logging.getLogger(__name__)

Base = declarative_base()

class User(Base):
    """User authentication and settings"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, nullable=False, unique=True)
    password_hash = Column(String, nullable=False)
    is_first_login = Column(Boolean, default=True)
    must_change_password = Column(Boolean, default=False)
    dashboard_layout = Column(Text, nullable=True)  # JSON string of GridStack layout
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    last_login = Column(DateTime, nullable=True)

class DockerHostDB(Base):
    """Docker host configuration"""
    __tablename__ = "docker_hosts"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    url = Column(String, nullable=False)
    tls_cert = Column(Text, nullable=True)
    tls_key = Column(Text, nullable=True)
    tls_ca = Column(Text, nullable=True)
    security_status = Column(String, nullable=True)  # 'secure', 'insecure', 'unknown'
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # Relationships
    auto_restart_configs = relationship("AutoRestartConfig", back_populates="host", cascade="all, delete-orphan")

class AutoRestartConfig(Base):
    """Auto-restart configuration for containers"""
    __tablename__ = "auto_restart_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    host_id = Column(String, ForeignKey("docker_hosts.id"))
    container_id = Column(String, nullable=False)
    container_name = Column(String, nullable=False)
    enabled = Column(Boolean, default=True)
    max_retries = Column(Integer, default=3)
    retry_delay = Column(Integer, default=30)
    restart_count = Column(Integer, default=0)
    last_restart = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # Relationships
    host = relationship("DockerHostDB", back_populates="auto_restart_configs")


class GlobalSettings(Base):
    """Global application settings"""
    __tablename__ = "global_settings"

    id = Column(Integer, primary_key=True, default=1)
    max_retries = Column(Integer, default=3)
    retry_delay = Column(Integer, default=30)
    default_auto_restart = Column(Boolean, default=False)
    polling_interval = Column(Integer, default=10)
    connection_timeout = Column(Integer, default=10)
    log_retention_days = Column(Integer, default=7)
    event_retention_days = Column(Integer, default=30)  # Keep events for 30 days
    enable_notifications = Column(Boolean, default=True)
    auto_cleanup_events = Column(Boolean, default=True)  # Auto cleanup old events
    alert_template = Column(Text, nullable=True)  # Global notification template
    blackout_windows = Column(JSON, nullable=True)  # Array of blackout time windows
    first_run_complete = Column(Boolean, default=False)  # Track if first run setup is complete
    timezone_offset = Column(Integer, default=0)  # Timezone offset in minutes from UTC
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class NotificationChannel(Base):
    """Notification channel configuration"""
    __tablename__ = "notification_channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    type = Column(String, nullable=False)  # telegram, discord, slack, pushover
    config = Column(JSON, nullable=False)  # Channel-specific configuration
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class AlertRuleDB(Base):
    """Alert rules for container state changes"""
    __tablename__ = "alert_rules"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    trigger_events = Column(JSON, nullable=True)  # list of Docker events that trigger alert
    trigger_states = Column(JSON, nullable=True)  # list of states that trigger alert
    notification_channels = Column(JSON, nullable=False)  # list of channel IDs
    cooldown_minutes = Column(Integer, default=15)  # prevent spam
    enabled = Column(Boolean, default=True)
    last_triggered = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # Relationships
    containers = relationship("AlertRuleContainer", back_populates="alert_rule", cascade="all, delete-orphan")

class AlertRuleContainer(Base):
    """Container+Host pairs for alert rules"""
    __tablename__ = "alert_rule_containers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_rule_id = Column(String, ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False)
    host_id = Column(String, ForeignKey("docker_hosts.id", ondelete="CASCADE"), nullable=False)
    container_name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.now)

    # Relationships
    alert_rule = relationship("AlertRuleDB", back_populates="containers")
    host = relationship("DockerHostDB")

    # Unique constraint to prevent duplicates
    __table_args__ = (
        UniqueConstraint('alert_rule_id', 'host_id', 'container_name', name='_alert_container_uc'),
    )

class EventLog(Base):
    """Comprehensive event logging for all DockMon activities"""
    __tablename__ = "event_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    correlation_id = Column(String, nullable=True)  # For linking related events

    # Event categorization
    category = Column(String, nullable=False)  # container, host, system, alert, notification
    event_type = Column(String, nullable=False)  # state_change, action_taken, error, etc.
    severity = Column(String, nullable=False, default='info')  # debug, info, warning, error, critical

    # Target information
    host_id = Column(String, nullable=True)
    host_name = Column(String, nullable=True)
    container_id = Column(String, nullable=True)
    container_name = Column(String, nullable=True)

    # Event details
    title = Column(String, nullable=False)  # Short description
    message = Column(Text, nullable=True)  # Detailed description
    old_state = Column(String, nullable=True)
    new_state = Column(String, nullable=True)
    triggered_by = Column(String, nullable=True)  # user, system, auto_restart, alert

    # Additional data
    details = Column(JSON, nullable=True)  # Structured additional data
    duration_ms = Column(Integer, nullable=True)  # For performance tracking

    # Timestamps
    timestamp = Column(DateTime, default=datetime.now, nullable=False)

    # Index for efficient queries
    __table_args__ = (
        {"sqlite_autoincrement": True},
    )

# Keep the old table for backward compatibility but mark as deprecated
class ContainerHistory(Base):
    """Historical data for container state changes - DEPRECATED: Use EventLog instead"""
    __tablename__ = "container_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    host_id = Column(String, nullable=False)
    container_id = Column(String, nullable=False)
    container_name = Column(String, nullable=False)
    event_type = Column(String, nullable=False)  # started, stopped, restarted, removed, crashed
    old_state = Column(String, nullable=True)
    new_state = Column(String, nullable=True)
    triggered_by = Column(String, nullable=True)  # manual, auto_restart, alert_action
    details = Column(JSON, nullable=True)
    timestamp = Column(DateTime, default=datetime.now)

    # Index for efficient queries
    __table_args__ = (
        {"sqlite_autoincrement": True},
    )

class DatabaseManager:
    """Database management and operations"""

    def __init__(self, db_path: str = "data/dockmon.db"):
        """Initialize database connection"""
        self.db_path = db_path

        # Ensure data directory exists
        data_dir = os.path.dirname(db_path)
        os.makedirs(data_dir, exist_ok=True)

        # Set secure permissions on data directory (rwx for owner only)
        try:
            os.chmod(data_dir, 0o700)
            logger.info(f"Set secure permissions (700) on data directory: {data_dir}")
        except OSError as e:
            logger.warning(f"Could not set permissions on data directory {data_dir}: {e}")

        # Create engine with connection pooling
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            echo=False
        )

        # Create session factory
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

        # Create tables if they don't exist
        Base.metadata.create_all(bind=self.engine)

        # Run database migrations
        self._run_migrations()

        # Set secure permissions on database file (rw for owner only)
        self._secure_database_file()

        # Initialize default settings if needed
        self._initialize_defaults()

    def _run_migrations(self):
        """Run database migrations for schema updates"""
        try:
            with self.get_session() as session:
                # Migration: Populate security_status for existing hosts
                hosts_without_security_status = session.query(DockerHostDB).filter(
                    DockerHostDB.security_status.is_(None)
                ).all()

                for host in hosts_without_security_status:
                    # Determine security status based on existing data
                    if host.url and not host.url.startswith('unix://'):
                        if host.tls_cert and host.tls_key:
                            host.security_status = 'secure'
                        else:
                            host.security_status = 'insecure'
                    # Unix socket connections don't need security status

                if hosts_without_security_status:
                    session.commit()
                    print(f"Migrated {len(hosts_without_security_status)} hosts with security status")

        except Exception as e:
            print(f"Migration warning: {e}")
            # Don't fail startup on migration errors

    def _secure_database_file(self):
        """Set secure file permissions on the SQLite database file"""
        try:
            if os.path.exists(self.db_path):
                # Set file permissions to 600 (read/write for owner only)
                os.chmod(self.db_path, 0o600)
                logger.info(f"Set secure permissions (600) on database file: {self.db_path}")
            else:
                # File doesn't exist yet - will be created by SQLAlchemy
                # Schedule permission setting for after first connection
                self._schedule_file_permissions()
        except OSError as e:
            logger.warning(f"Could not set permissions on database file {self.db_path}: {e}")

    def _schedule_file_permissions(self):
        """Schedule file permission setting for after database file is created"""
        # Create a connection to ensure the file exists
        with self.engine.connect() as conn:
            pass

        # Now set permissions
        try:
            if os.path.exists(self.db_path):
                os.chmod(self.db_path, 0o600)
                logger.info(f"Set secure permissions (600) on newly created database file: {self.db_path}")
        except OSError as e:
            logger.warning(f"Could not set permissions on newly created database file {self.db_path}: {e}")

    def _initialize_defaults(self):
        """Initialize default settings if they don't exist"""
        with self.get_session() as session:
            # Check if global settings exist
            settings = session.query(GlobalSettings).first()
            if not settings:
                settings = GlobalSettings()
                session.add(settings)
                session.commit()

    def get_session(self) -> Session:
        """Get a database session"""
        return self.SessionLocal()

    # Docker Host Operations
    def add_host(self, host_data: dict) -> DockerHostDB:
        """Add a new Docker host"""
        with self.get_session() as session:
            host = DockerHostDB(**host_data)
            session.add(host)
            session.commit()
            session.refresh(host)
            return host

    def get_hosts(self, active_only: bool = True) -> List[DockerHostDB]:
        """Get all Docker hosts ordered by creation time"""
        with self.get_session() as session:
            query = session.query(DockerHostDB)
            if active_only:
                query = query.filter(DockerHostDB.is_active == True)
            # Order by created_at to ensure consistent ordering (oldest first)
            query = query.order_by(DockerHostDB.created_at)
            return query.all()

    def get_host(self, host_id: str) -> Optional[DockerHostDB]:
        """Get a specific Docker host"""
        with self.get_session() as session:
            return session.query(DockerHostDB).filter(DockerHostDB.id == host_id).first()

    def update_host(self, host_id: str, updates: dict) -> Optional[DockerHostDB]:
        """Update a Docker host"""
        with self.get_session() as session:
            host = session.query(DockerHostDB).filter(DockerHostDB.id == host_id).first()
            if host:
                for key, value in updates.items():
                    setattr(host, key, value)
                host.updated_at = datetime.now()
                session.commit()
                session.refresh(host)
            return host

    def delete_host(self, host_id: str) -> bool:
        """Delete a Docker host and clean up related alert rules"""
        with self.get_session() as session:
            host = session.query(DockerHostDB).filter(DockerHostDB.id == host_id).first()
            if not host:
                return False

            # Get all alert rules
            all_rules = session.query(AlertRuleDB).all()

            # Process each alert rule to remove containers from the deleted host
            for rule in all_rules:
                if not rule.containers:
                    continue

                # Filter out containers from the deleted host
                # rule.containers is a list of AlertRuleContainer objects
                remaining_containers = [
                    c for c in rule.containers
                    if c.host_id != host_id
                ]

                if len(remaining_containers) == 0:
                    # No containers left, delete the entire alert
                    session.delete(rule)
                    logger.info(f"Deleted alert rule '{rule.name}' (all containers were on deleted host {host_id})")
                elif len(remaining_containers) < len(rule.containers):
                    # Some containers remain, update the alert
                    rule.containers = remaining_containers
                    rule.updated_at = datetime.now()
                    logger.info(f"Updated alert rule '{rule.name}' (removed containers from host {host_id})")

            # Delete the host
            session.delete(host)
            session.commit()
            return True

    # Auto-Restart Configuration
    def get_auto_restart_config(self, host_id: str, container_id: str) -> Optional[AutoRestartConfig]:
        """Get auto-restart configuration for a container"""
        with self.get_session() as session:
            return session.query(AutoRestartConfig).filter(
                AutoRestartConfig.host_id == host_id,
                AutoRestartConfig.container_id == container_id
            ).first()

    def set_auto_restart(self, host_id: str, container_id: str, container_name: str, enabled: bool):
        """Set auto-restart configuration for a container"""
        with self.get_session() as session:
            config = session.query(AutoRestartConfig).filter(
                AutoRestartConfig.host_id == host_id,
                AutoRestartConfig.container_id == container_id
            ).first()

            if config:
                config.enabled = enabled
                config.updated_at = datetime.now()
                if not enabled:
                    config.restart_count = 0
            else:
                config = AutoRestartConfig(
                    host_id=host_id,
                    container_id=container_id,
                    container_name=container_name,
                    enabled=enabled
                )
                session.add(config)

            session.commit()

    def increment_restart_count(self, host_id: str, container_id: str):
        """Increment restart count for a container"""
        with self.get_session() as session:
            config = session.query(AutoRestartConfig).filter(
                AutoRestartConfig.host_id == host_id,
                AutoRestartConfig.container_id == container_id
            ).first()

            if config:
                config.restart_count += 1
                config.last_restart = datetime.now()
                session.commit()

    def reset_restart_count(self, host_id: str, container_id: str):
        """Reset restart count for a container"""
        with self.get_session() as session:
            config = session.query(AutoRestartConfig).filter(
                AutoRestartConfig.host_id == host_id,
                AutoRestartConfig.container_id == container_id
            ).first()

            if config:
                config.restart_count = 0
                session.commit()

    # Global Settings
    def get_settings(self) -> GlobalSettings:
        """Get global settings"""
        with self.get_session() as session:
            return session.query(GlobalSettings).first()

    def update_settings(self, updates: dict) -> GlobalSettings:
        """Update global settings"""
        with self.get_session() as session:
            settings = session.query(GlobalSettings).first()
            for key, value in updates.items():
                if hasattr(settings, key):
                    setattr(settings, key, value)
            settings.updated_at = datetime.now()
            session.commit()
            session.refresh(settings)
            return settings

    # Notification Channels
    def add_notification_channel(self, channel_data: dict) -> NotificationChannel:
        """Add a notification channel"""
        with self.get_session() as session:
            channel = NotificationChannel(**channel_data)
            session.add(channel)
            session.commit()
            session.refresh(channel)
            return channel

    def get_notification_channels(self, enabled_only: bool = True) -> List[NotificationChannel]:
        """Get all notification channels"""
        with self.get_session() as session:
            query = session.query(NotificationChannel)
            if enabled_only:
                query = query.filter(NotificationChannel.enabled == True)
            return query.all()

    def get_notification_channels_by_ids(self, channel_ids: List[int]) -> List[NotificationChannel]:
        """Get notification channels by their IDs"""
        with self.get_session() as session:
            channels = session.query(NotificationChannel).filter(
                NotificationChannel.id.in_(channel_ids),
                NotificationChannel.enabled == True
            ).all()

            # Detach from session to avoid lazy loading issues
            session.expunge_all()
            return channels

    def update_notification_channel(self, channel_id: int, updates: dict) -> Optional[NotificationChannel]:
        """Update a notification channel"""
        with self.get_session() as session:
            channel = session.query(NotificationChannel).filter(NotificationChannel.id == channel_id).first()
            if channel:
                for key, value in updates.items():
                    setattr(channel, key, value)
                channel.updated_at = datetime.now()
                session.commit()
                session.refresh(channel)
            return channel

    def delete_notification_channel(self, channel_id: int) -> bool:
        """Delete a notification channel"""
        with self.get_session() as session:
            channel = session.query(NotificationChannel).filter(NotificationChannel.id == channel_id).first()
            if channel:
                session.delete(channel)
                session.commit()
                return True
            return False

    # Alert Rules
    def add_alert_rule(self, rule_data: dict) -> AlertRuleDB:
        """Add an alert rule with container+host pairs"""
        with self.get_session() as session:
            # Extract containers list if present
            containers_data = rule_data.pop('containers', None)

            rule = AlertRuleDB(**rule_data)
            session.add(rule)
            session.flush()  # Flush to get the ID without committing

            # Add container+host pairs if provided
            if containers_data:
                for container in containers_data:
                    container_pair = AlertRuleContainer(
                        alert_rule_id=rule.id,
                        host_id=container['host_id'],
                        container_name=container['container_name']
                    )
                    session.add(container_pair)

            session.commit()

            # Create a detached copy with all needed attributes
            rule_dict = {
                'id': rule.id,
                'name': rule.name,
                'trigger_events': rule.trigger_events,
                'trigger_states': rule.trigger_states,
                'notification_channels': rule.notification_channels,
                'cooldown_minutes': rule.cooldown_minutes,
                'enabled': rule.enabled,
                'last_triggered': rule.last_triggered,
                'created_at': rule.created_at,
                'updated_at': rule.updated_at
            }

            # Return a new instance that's not attached to the session
            detached_rule = AlertRuleDB(**rule_dict)
            detached_rule.containers = []  # Initialize empty containers list

            return detached_rule

    def get_alert_rule(self, rule_id: str) -> Optional[AlertRuleDB]:
        """Get a single alert rule by ID"""
        with self.get_session() as session:
            from sqlalchemy.orm import joinedload
            rule = session.query(AlertRuleDB).options(joinedload(AlertRuleDB.containers)).filter(AlertRuleDB.id == rule_id).first()
            if rule:
                session.expunge(rule)
            return rule

    def get_alert_rules(self, enabled_only: bool = True) -> List[AlertRuleDB]:
        """Get all alert rules"""
        with self.get_session() as session:
            from sqlalchemy.orm import joinedload
            query = session.query(AlertRuleDB).options(joinedload(AlertRuleDB.containers))
            if enabled_only:
                query = query.filter(AlertRuleDB.enabled == True)
            rules = query.all()
            # Detach from session to avoid lazy loading issues
            for rule in rules:
                session.expunge(rule)
            return rules

    def update_alert_rule(self, rule_id: str, updates: dict) -> Optional[AlertRuleDB]:
        """Update an alert rule and its container+host pairs"""
        with self.get_session() as session:
            from sqlalchemy.orm import joinedload
            rule = session.query(AlertRuleDB).options(joinedload(AlertRuleDB.containers)).filter(AlertRuleDB.id == rule_id).first()
            if rule:
                # Extract containers list if present
                containers_data = updates.pop('containers', None)

                # Update rule fields
                for key, value in updates.items():
                    setattr(rule, key, value)
                rule.updated_at = datetime.now()

                # Update container+host pairs if provided
                if containers_data is not None:
                    # Delete existing container pairs
                    session.query(AlertRuleContainer).filter(
                        AlertRuleContainer.alert_rule_id == rule_id
                    ).delete()

                    # Add new container pairs
                    for container in containers_data:
                        container_pair = AlertRuleContainer(
                            alert_rule_id=rule_id,
                            host_id=container['host_id'],
                            container_name=container['container_name']
                        )
                        session.add(container_pair)

                session.commit()
                session.refresh(rule)
                # Load containers relationship
                _ = rule.containers
                session.expunge(rule)
            return rule

    def delete_alert_rule(self, rule_id: str) -> bool:
        """Delete an alert rule"""
        with self.get_session() as session:
            rule = session.query(AlertRuleDB).filter(AlertRuleDB.id == rule_id).first()
            if rule:
                session.delete(rule)
                session.commit()
                return True
            return False

    def get_alerts_dependent_on_channel(self, channel_id: int) -> List[dict]:
        """Find alerts that would be orphaned if this channel is deleted (only have this one channel)"""
        with self.get_session() as session:
            all_rules = session.query(AlertRuleDB).all()
            dependent_alerts = []

            for rule in all_rules:
                # Parse notification_channels JSON
                channels = rule.notification_channels if isinstance(rule.notification_channels, list) else []
                # Check if this is the ONLY channel for this alert
                if len(channels) == 1 and channel_id in channels:
                    dependent_alerts.append({
                        'id': rule.id,
                        'name': rule.name
                    })

            return dependent_alerts

    # Container History
    def add_container_event(self, event_data: dict):
        """Add a container history event"""
        with self.get_session() as session:
            event = ContainerHistory(**event_data)
            session.add(event)
            session.commit()

    def get_container_history(self, host_id: str = None, container_id: str = None,
                            limit: int = 100) -> List[ContainerHistory]:
        """Get container history events"""
        with self.get_session() as session:
            query = session.query(ContainerHistory)

            if host_id:
                query = query.filter(ContainerHistory.host_id == host_id)
            if container_id:
                query = query.filter(ContainerHistory.container_id == container_id)

            return query.order_by(ContainerHistory.timestamp.desc()).limit(limit).all()

    def cleanup_old_history(self, days: int = 7):
        """Clean up old history records"""
        with self.get_session() as session:
            cutoff_date = datetime.now() - timedelta(days=days)
            session.query(ContainerHistory).filter(
                ContainerHistory.timestamp < cutoff_date
            ).delete()
            session.commit()

    # Event Logging Operations
    def add_event(self, event_data: dict) -> EventLog:
        """Add an event to the event log"""
        with self.get_session() as session:
            event = EventLog(**event_data)
            session.add(event)
            session.commit()
            session.refresh(event)
            return event

    def get_events(self,
                   category: Optional[str] = None,
                   event_type: Optional[str] = None,
                   severity: Optional[str] = None,
                   host_id: Optional[str] = None,
                   container_id: Optional[str] = None,
                   container_name: Optional[str] = None,
                   start_date: Optional[datetime] = None,
                   end_date: Optional[datetime] = None,
                   correlation_id: Optional[str] = None,
                   search: Optional[str] = None,
                   limit: int = 100,
                   offset: int = 0) -> tuple[List[EventLog], int]:
        """Get events with filtering and pagination - returns (events, total_count)"""
        with self.get_session() as session:
            query = session.query(EventLog)

            # Apply filters
            if category:
                query = query.filter(EventLog.category == category)
            if event_type:
                query = query.filter(EventLog.event_type == event_type)
            if severity:
                query = query.filter(EventLog.severity == severity)
            if host_id:
                query = query.filter(EventLog.host_id == host_id)
            if container_id:
                query = query.filter(EventLog.container_id == container_id)
            if container_name:
                query = query.filter(EventLog.container_name.like(f'%{container_name}%'))
            if start_date:
                query = query.filter(EventLog.timestamp >= start_date)
            if end_date:
                query = query.filter(EventLog.timestamp <= end_date)
            if correlation_id:
                query = query.filter(EventLog.correlation_id == correlation_id)
            if search:
                search_term = f'%{search}%'
                query = query.filter(
                    (EventLog.title.like(search_term)) |
                    (EventLog.message.like(search_term)) |
                    (EventLog.container_name.like(search_term))
                )

            # Get total count for pagination
            total_count = query.count()

            # Apply ordering, limit and offset
            events = query.order_by(EventLog.timestamp.desc()).offset(offset).limit(limit).all()

            return events, total_count

    def get_event_by_id(self, event_id: int) -> Optional[EventLog]:
        """Get a specific event by ID"""
        with self.get_session() as session:
            return session.query(EventLog).filter(EventLog.id == event_id).first()

    def get_events_by_correlation(self, correlation_id: str) -> List[EventLog]:
        """Get all events with the same correlation ID"""
        with self.get_session() as session:
            return session.query(EventLog).filter(
                EventLog.correlation_id == correlation_id
            ).order_by(EventLog.timestamp.asc()).all()

    def cleanup_old_events(self, days: int = 30):
        """Clean up old event logs"""
        with self.get_session() as session:
            cutoff_date = datetime.now() - timedelta(days=days)
            deleted_count = session.query(EventLog).filter(
                EventLog.timestamp < cutoff_date
            ).delete()
            session.commit()
            return deleted_count

    def get_event_statistics(self,
                           start_date: Optional[datetime] = None,
                           end_date: Optional[datetime] = None) -> Dict[str, Any]:
        """Get event statistics for dashboard"""
        with self.get_session() as session:
            query = session.query(EventLog)

            if start_date:
                query = query.filter(EventLog.timestamp >= start_date)
            if end_date:
                query = query.filter(EventLog.timestamp <= end_date)

            total_events = query.count()

            # Count by category
            category_counts = {}
            for category, count in session.query(EventLog.category,
                                               session.func.count(EventLog.id)).group_by(EventLog.category).all():
                category_counts[category] = count

            # Count by severity
            severity_counts = {}
            for severity, count in session.query(EventLog.severity,
                                               session.func.count(EventLog.id)).group_by(EventLog.severity).all():
                severity_counts[severity] = count

            return {
                'total_events': total_events,
                'category_counts': category_counts,
                'severity_counts': severity_counts,
                'period_start': start_date.isoformat() if start_date else None,
                'period_end': end_date.isoformat() if end_date else None
            }


    # User management methods
    def _hash_password(self, password: str) -> str:
        """Hash a password using bcrypt with salt"""
        # Generate salt and hash password
        salt = bcrypt.gensalt(rounds=12)  # 12 rounds is a good balance of security/speed
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')

    def _verify_password(self, password: str, hashed: str) -> bool:
        """Verify a password against a bcrypt hash"""
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

    def get_or_create_default_user(self) -> None:
        """Create default admin user if no users exist"""
        with self.get_session() as session:
            # Check if ANY user exists (not just 'admin')
            user_count = session.query(User).count()
            if user_count == 0:
                # Only create default admin user if no users exist at all
                user = User(
                    username="admin",
                    password_hash=self._hash_password("dockmon123"),  # Default password
                    is_first_login=True,
                    must_change_password=True
                )
                session.add(user)
                session.commit()
                logger.info("Created default admin user")

    def verify_user_credentials(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """Verify user credentials and return user info if valid"""
        with self.get_session() as session:
            user = session.query(User).filter(User.username == username).first()
            if user and self._verify_password(password, user.password_hash):
                # Update last login
                user.last_login = datetime.now()
                session.commit()
                return {
                    "username": user.username,
                    "is_first_login": user.is_first_login,
                    "must_change_password": user.must_change_password
                }
            return None

    def change_user_password(self, username: str, new_password: str) -> bool:
        """Change user password"""
        with self.get_session() as session:
            user = session.query(User).filter(User.username == username).first()
            if user:
                user.password_hash = self._hash_password(new_password)
                user.is_first_login = False
                user.must_change_password = False
                user.updated_at = datetime.now()
                session.commit()
                logger.info(f"Password changed for user: {username}")
                return True
            return False

    def username_exists(self, username: str) -> bool:
        """Check if username already exists"""
        with self.get_session() as session:
            user = session.query(User).filter(User.username == username).first()
            return user is not None

    def change_username(self, old_username: str, new_username: str) -> bool:
        """Change user's username"""
        with self.get_session() as session:
            user = session.query(User).filter(User.username == old_username).first()
            if user:
                user.username = new_username
                user.updated_at = datetime.now()
                session.commit()
                logger.info(f"Username changed from {old_username} to {new_username}")
                return True
            return False

    def reset_user_password(self, username: str, new_password: str = None) -> str:
        """Reset user password (for CLI tool)"""
        with self.get_session() as session:
            user = session.query(User).filter(User.username == username).first()
            if not user:
                return None

            # Generate new password if not provided
            if not new_password:
                new_password = secrets.token_urlsafe(12)

            user.password_hash = self._hash_password(new_password)
            user.must_change_password = True
            user.updated_at = datetime.now()
            session.commit()
            logger.info(f"Password reset for user: {username}")
            return new_password

    def list_users(self) -> List[str]:
        """List all usernames"""
        with self.get_session() as session:
            users = session.query(User.username).all()
            return [u[0] for u in users]

    def get_dashboard_layout(self, username: str) -> Optional[str]:
        """Get dashboard layout for a user"""
        with self.get_session() as session:
            user = session.query(User).filter(User.username == username).first()
            if user:
                return user.dashboard_layout
            return None

    def save_dashboard_layout(self, username: str, layout: str) -> bool:
        """Save dashboard layout for a user"""
        with self.get_session() as session:
            user = session.query(User).filter(User.username == username).first()
            if user:
                user.dashboard_layout = layout
                user.updated_at = datetime.now()
                session.commit()
                return True
            return False