"""
Database models and operations for DockMon
Uses SQLite for persistent storage of configuration and settings
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy import create_engine, Column, String, Integer, BigInteger, Boolean, DateTime, JSON, ForeignKey, Text, UniqueConstraint, CheckConstraint, text, Float, func, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from sqlalchemy.pool import StaticPool
import json
import os
import logging
import secrets
import bcrypt
import uuid

from utils.keys import make_composite_key

logger = logging.getLogger(__name__)

# Singleton instance and thread lock for DatabaseManager
# CRITICAL: Only ONE DatabaseManager instance should exist per process to avoid:
# - Multiple SQLAlchemy engine/connection pools (resource waste)
# - Duplicate migration runs (SQLite lock conflicts)
# - Inconsistent state across different instances
import threading
_database_manager_instance: Optional['DatabaseManager'] = None
_database_manager_lock = threading.Lock()


def utcnow():
    """Helper to get timezone-aware UTC datetime for database defaults"""
    return datetime.now(timezone.utc)


Base = declarative_base()

class User(Base):
    """User authentication and settings"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, nullable=False, unique=True)
    password_hash = Column(String, nullable=False)
    display_name = Column(String, nullable=True)  # Optional friendly display name
    is_first_login = Column(Boolean, default=True)
    must_change_password = Column(Boolean, default=False)
    dashboard_layout_v2 = Column(Text, nullable=True)  # JSON string of react-grid-layout (v2)
    sidebar_collapsed = Column(Boolean, default=False)  # Sidebar collapse state (v2)
    view_mode = Column(String, nullable=True)  # Dashboard view mode: 'compact' | 'standard' | 'expanded' (Phase 4)
    event_sort_order = Column(String, default='desc')  # 'desc' (newest first) or 'asc' (oldest first)
    modal_preferences = Column(Text, nullable=True)  # JSON string of modal size/position preferences
    prefs = Column(Text, nullable=True)  # JSON string of user preferences (dashboard, table sorts, etc.)
    simplified_workflow = Column(Boolean, default=True)  # Skip drawer, open modal directly
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    last_login = Column(DateTime, nullable=True)

class UserPrefs(Base):
    """User preferences table (theme and defaults)"""
    __tablename__ = "user_prefs"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    theme = Column(String, default="dark")
    defaults_json = Column(Text, nullable=True)  # JSON string of default preferences
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

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
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    # Phase 3d - Host organization
    tags = Column(Text, nullable=True)  # JSON array of tags
    description = Column(Text, nullable=True)  # Optional host description
    # Phase 5 - System information
    os_type = Column(String, nullable=True)  # "linux", "windows", etc.
    os_version = Column(String, nullable=True)  # e.g., "Ubuntu 22.04.3 LTS"
    kernel_version = Column(String, nullable=True)  # e.g., "5.15.0-88-generic"
    docker_version = Column(String, nullable=True)  # e.g., "24.0.6"
    daemon_started_at = Column(String, nullable=True)  # ISO timestamp when Docker daemon started
    # System resources
    total_memory = Column(BigInteger, nullable=True)  # Total memory in bytes
    num_cpus = Column(Integer, nullable=True)  # Number of CPUs

    # Relationships
    auto_restart_configs = relationship("AutoRestartConfig", back_populates="host", cascade="all, delete-orphan")

class AutoRestartConfig(Base):
    """Auto-restart configuration for containers"""
    __tablename__ = "auto_restart_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    host_id = Column(String, ForeignKey("docker_hosts.id", ondelete="CASCADE"))
    container_id = Column(String, nullable=False)
    container_name = Column(String, nullable=False)
    enabled = Column(Boolean, default=True)
    max_retries = Column(Integer, default=3)
    retry_delay = Column(Integer, default=30)
    restart_count = Column(Integer, default=0)
    last_restart = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    host = relationship("DockerHostDB", back_populates="auto_restart_configs")


class ContainerDesiredState(Base):
    """Desired state configuration for containers"""
    __tablename__ = "container_desired_states"

    id = Column(Integer, primary_key=True, autoincrement=True)
    host_id = Column(String, ForeignKey("docker_hosts.id", ondelete="CASCADE"))
    container_id = Column(String, nullable=False)
    container_name = Column(String, nullable=False)
    desired_state = Column(String, default='unspecified')  # 'should_run', 'on_demand', 'unspecified'
    custom_tags = Column(Text, nullable=True)  # Comma-separated custom tags
    update_policy = Column(Text, nullable=True)  # 'allow', 'warn', 'block', or NULL (auto-detect)
    web_ui_url = Column(Text, nullable=True)  # URL to container's web interface
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    host = relationship("DockerHostDB")


class BatchJob(Base):
    """Batch job for bulk operations"""
    __tablename__ = "batch_jobs"

    id = Column(String, primary_key=True)  # e.g., "job_abc123"
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    scope = Column(String, nullable=False)  # 'container' (hosts in future)
    action = Column(String, nullable=False)  # 'start', 'stop', 'restart', etc.
    params = Column(Text, nullable=True)  # JSON string of action parameters
    status = Column(String, default='queued')  # 'queued', 'running', 'completed', 'partial', 'failed'
    total_items = Column(Integer, default=0)
    completed_items = Column(Integer, default=0)
    success_items = Column(Integer, default=0)
    error_items = Column(Integer, default=0)
    skipped_items = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    user = relationship("User")
    items = relationship("BatchJobItem", back_populates="job", cascade="all, delete-orphan")


class BatchJobItem(Base):
    """Individual item in a batch job"""
    __tablename__ = "batch_job_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, ForeignKey("batch_jobs.id"), nullable=False)
    container_id = Column(String, nullable=False)
    container_name = Column(String, nullable=False)
    host_id = Column(String, nullable=False)
    host_name = Column(String, nullable=True)
    status = Column(String, default='queued')  # 'queued', 'running', 'success', 'error', 'skipped'
    message = Column(Text, nullable=True)  # Success message or error details
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    job = relationship("BatchJob", back_populates="items")


class GlobalSettings(Base):
    """Global application settings"""
    __tablename__ = "global_settings"

    id = Column(Integer, primary_key=True, default=1)
    __table_args__ = (
        # Ensure only one settings row exists
        CheckConstraint('id = 1', name='single_settings_row'),
    )
    max_retries = Column(Integer, default=3)
    retry_delay = Column(Integer, default=30)
    default_auto_restart = Column(Boolean, default=False)
    polling_interval = Column(Integer, default=2)
    connection_timeout = Column(Integer, default=10)
    event_retention_days = Column(Integer, default=60)  # Keep events for 60 days (max 365)
    enable_notifications = Column(Boolean, default=True)
    auto_cleanup_events = Column(Boolean, default=True)  # Auto cleanup old events
    unused_tag_retention_days = Column(Integer, default=30)  # Delete unused tags after N days (0 = never)
    alert_template = Column(Text, nullable=True)  # Global notification template (default)
    alert_template_metric = Column(Text, nullable=True)  # Metric-based alert template
    alert_template_state_change = Column(Text, nullable=True)  # State change alert template
    alert_template_health = Column(Text, nullable=True)  # Health check alert template
    alert_template_update = Column(Text, nullable=True)  # Container update alert template
    blackout_windows = Column(JSON, nullable=True)  # Array of blackout time windows
    first_run_complete = Column(Boolean, default=False)  # Track if first run setup is complete
    polling_interval_migrated = Column(Boolean, default=False)  # Track if polling interval has been migrated to 2s
    timezone_offset = Column(Integer, default=0)  # Timezone offset in minutes from UTC
    show_host_stats = Column(Boolean, default=True)  # Show host statistics graphs on dashboard
    show_container_stats = Column(Boolean, default=True)  # Show container statistics on dashboard

    # Container update settings
    auto_update_enabled_default = Column(Boolean, default=False)  # Enable auto-updates by default for new containers
    update_check_interval_hours = Column(Integer, default=24)  # How often to check for updates (hours)
    update_check_time = Column(Text, default="02:00")  # Time of day to run checks (HH:MM format, 24-hour)
    skip_compose_containers = Column(Boolean, default=True)  # Skip Docker Compose-managed containers
    health_check_timeout_seconds = Column(Integer, default=10)  # Health check timeout (seconds)

    # Alert system settings
    alert_retention_days = Column(Integer, default=90)  # Keep resolved alerts for N days (0 = keep forever)

    # Version tracking and upgrade notifications
    app_version = Column(String, default="2.0.0")  # Current application version
    upgrade_notice_dismissed = Column(Boolean, default=True)  # Whether user has seen v2 upgrade notice (False for v1→v2 upgrades set by migration)
    last_viewed_release_notes = Column(String, nullable=True)  # Last version of release notes user viewed

    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

class ContainerUpdate(Base):
    """Container update tracking"""
    __tablename__ = "container_updates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    container_id = Column(Text, nullable=False, unique=True)  # Composite: host_id:short_container_id
    host_id = Column(Text, ForeignKey("docker_hosts.id", ondelete="CASCADE"), nullable=False)

    # Current state
    current_image = Column(Text, nullable=False)
    current_digest = Column(Text, nullable=False)

    # Latest available
    latest_image = Column(Text, nullable=True)
    latest_digest = Column(Text, nullable=True)
    update_available = Column(Boolean, default=False, nullable=False)

    # Tracking settings
    floating_tag_mode = Column(Text, default='exact', nullable=False)  # exact|minor|major|latest
    auto_update_enabled = Column(Boolean, default=False, nullable=False)
    health_check_strategy = Column(Text, default='docker', nullable=False)  # docker|warmup|http
    health_check_url = Column(Text, nullable=True)

    # Metadata
    last_checked_at = Column(DateTime, nullable=True)
    last_updated_at = Column(DateTime, nullable=True)
    registry_url = Column(Text, nullable=True)
    platform = Column(Text, nullable=True)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class ContainerHttpHealthCheck(Base):
    """HTTP/HTTPS health check configuration for containers"""
    __tablename__ = "container_http_health_checks"

    container_id = Column(Text, primary_key=True)  # Composite: host_id:container_id
    host_id = Column(Text, ForeignKey("docker_hosts.id", ondelete="CASCADE"), nullable=False)

    # Configuration
    enabled = Column(Boolean, default=False, nullable=False)
    url = Column(Text, nullable=False)
    method = Column(Text, default='GET', nullable=False)
    expected_status_codes = Column(Text, default='200', nullable=False)
    timeout_seconds = Column(Integer, default=10, nullable=False)
    check_interval_seconds = Column(Integer, default=60, nullable=False)
    follow_redirects = Column(Boolean, default=True, nullable=False)
    verify_ssl = Column(Boolean, default=True, nullable=False)

    # Advanced config (JSON)
    headers_json = Column(Text, nullable=True)
    auth_config_json = Column(Text, nullable=True)

    # State tracking
    current_status = Column(Text, default='unknown', nullable=False)
    last_checked_at = Column(DateTime, nullable=True)
    last_success_at = Column(DateTime, nullable=True)
    last_failure_at = Column(DateTime, nullable=True)
    consecutive_successes = Column(Integer, default=0, nullable=False)
    consecutive_failures = Column(Integer, default=0, nullable=False)
    last_response_time_ms = Column(Integer, nullable=True)
    last_error_message = Column(Text, nullable=True)

    # Auto-restart integration
    auto_restart_on_failure = Column(Boolean, default=False, nullable=False)
    failure_threshold = Column(Integer, default=3, nullable=False)
    success_threshold = Column(Integer, default=1, nullable=False)  # Consecutive successes to mark healthy

    # Metadata
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (
        Index('idx_http_health_enabled', 'enabled'),
        Index('idx_http_health_host', 'host_id'),
        Index('idx_http_health_status', 'current_status'),
    )


class UpdatePolicy(Base):
    """Update validation policy rules"""
    __tablename__ = "update_policies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(Text, nullable=False)  # 'databases', 'proxies', 'monitoring', 'custom', 'critical'
    pattern = Column(Text, nullable=False)   # Pattern to match against image/container name
    enabled = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint('category', 'pattern', name='uq_update_policies_category_pattern'),
    )


class NotificationChannel(Base):
    """Notification channel configuration"""
    __tablename__ = "notification_channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    type = Column(String, nullable=False)  # telegram, discord, slack, pushover
    config = Column(JSON, nullable=False)  # Channel-specific configuration
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

# ==================== Alerts v2 Tables ====================

class AlertRuleV2(Base):
    """Alert rules v2 - supports metric-driven and event-driven rules"""
    __tablename__ = "alert_rules_v2"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    scope = Column(String, nullable=False)  # 'host' | 'container' | 'group'
    kind = Column(String, nullable=False)  # 'cpu_high', 'unhealthy', 'churn', etc.
    enabled = Column(Boolean, default=True)

    # Matching/Selectors
    host_selector_json = Column(Text, nullable=True)  # JSON: {"include_all": true, "exclude": [...]}
    container_selector_json = Column(Text, nullable=True)
    labels_json = Column(Text, nullable=True)

    # Conditions (metric-driven rules)
    metric = Column(String, nullable=True)  # 'docker_cpu_workload_pct', etc.
    operator = Column(String, nullable=True)  # '>=', '<=', '=='
    threshold = Column(Float, nullable=True)
    duration_seconds = Column(Integer, nullable=True)  # 300 for 'for 5m'
    occurrences = Column(Integer, nullable=True)  # 3 for '3/5m'

    # Clearing
    clear_threshold = Column(Float, nullable=True)
    clear_duration_seconds = Column(Integer, nullable=True)

    # Behavior
    severity = Column(String, nullable=False)  # 'info' | 'warning' | 'critical'
    cooldown_seconds = Column(Integer, default=300)
    depends_on_json = Column(Text, nullable=True)  # JSON: ["host_missing", ...]
    auto_resolve = Column(Boolean, default=False)  # Auto-resolve alert immediately after notification (for update alerts)
    suppress_during_updates = Column(Boolean, default=False)  # Suppress this alert during container updates, re-evaluate after update completes

    # Notifications
    notify_channels_json = Column(Text, nullable=True)  # JSON: ["slack", "telegram"]
    custom_template = Column(Text, nullable=True)  # Custom message template for this rule

    # Lifecycle
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    created_by = Column(String, nullable=True)
    updated_by = Column(String, nullable=True)
    version = Column(Integer, default=1)  # Incremented on each update

    # Indexes
    __table_args__ = (
        {"sqlite_autoincrement": True},
    )


class AlertV2(Base):
    """Alert instances v2 - stateful, deduplicated alerts"""
    __tablename__ = "alerts_v2"

    id = Column(String, primary_key=True)
    dedup_key = Column(String, nullable=False, unique=True)  # {kind}|{scope_type}:{scope_id}
    scope_type = Column(String, nullable=False)  # 'host' | 'container' | 'group'
    scope_id = Column(String, nullable=False)
    kind = Column(String, nullable=False)  # 'cpu_high', 'unhealthy', etc.
    severity = Column(String, nullable=False)  # 'info' | 'warning' | 'critical'
    state = Column(String, nullable=False)  # 'open' | 'snoozed' | 'resolved'
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)

    # Timestamps
    first_seen = Column(DateTime, nullable=False)
    last_seen = Column(DateTime, nullable=False)
    occurrences = Column(Integer, default=1, nullable=False)
    snoozed_until = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    resolved_reason = Column(String, nullable=True)  # 'auto_clear' | 'entity_gone' | 'expired' | 'manual'

    # Context & traceability
    rule_id = Column(String, ForeignKey("alert_rules_v2.id", ondelete="SET NULL"), nullable=True)
    rule_version = Column(Integer, nullable=True)
    current_value = Column(Float, nullable=True)
    threshold = Column(Float, nullable=True)
    rule_snapshot = Column(Text, nullable=True)  # JSON of rule at opening
    labels_json = Column(Text, nullable=True)  # {"env": "prod", "tier": "web"}
    host_name = Column(String, nullable=True)  # Friendly name for display
    host_id = Column(String, nullable=True)  # Host ID for linking
    container_name = Column(String, nullable=True)  # Friendly name for display
    event_context_json = Column(Text, nullable=True)  # Event-specific data for template variables (old_state, new_state, exit_code, image, etc.)

    # Notification tracking
    notified_at = Column(DateTime, nullable=True)
    notification_count = Column(Integer, default=0)
    suppressed_by_blackout = Column(Boolean, default=False, nullable=False)  # Alert suppressed during blackout window

    # Relationships
    rule = relationship("AlertRuleV2", foreign_keys=[rule_id])
    annotations = relationship("AlertAnnotation", back_populates="alert", cascade="all, delete-orphan")

    # Composite indexes for common queries
    __table_args__ = (
        Index('idx_alertv2_state', 'state'),  # Filter by state (open/resolved)
        Index('idx_alertv2_scope', 'scope_type', 'scope_id'),  # Filter by scope (host/container)
        Index('idx_alertv2_severity', 'severity'),  # Filter by severity
        Index('idx_alertv2_first_seen', 'first_seen'),  # Sort by first_seen
        Index('idx_alertv2_last_seen', last_seen.desc()),  # Sort by last_seen DESC (most recent first)
        Index('idx_alertv2_host_id', 'host_id'),  # Filter by host
        Index('idx_alertv2_rule_id', 'rule_id'),  # FK lookup performance
        {"sqlite_autoincrement": True},
    )


class AlertAnnotation(Base):
    """User annotations on alerts"""
    __tablename__ = "alert_annotations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_id = Column(String, ForeignKey("alerts_v2.id", ondelete="CASCADE"), nullable=False)
    timestamp = Column(DateTime, default=utcnow, nullable=False)
    user = Column(String, nullable=True)
    text = Column(Text, nullable=False)

    # Relationship
    alert = relationship("AlertV2", back_populates="annotations")


class RuleRuntime(Base):
    """Rule evaluation runtime state - sliding windows, breach tracking"""
    __tablename__ = "rule_runtime"

    dedup_key = Column(String, primary_key=True)
    rule_id = Column(String, ForeignKey("alert_rules_v2.id", ondelete="CASCADE"), nullable=False)
    state_json = Column(Text, nullable=False)  # JSON state (see docs for format)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    # Relationship
    rule = relationship("AlertRuleV2", foreign_keys=[rule_id])


class RuleEvaluation(Base):
    """Rule evaluation history for debugging (24h retention)"""
    __tablename__ = "rule_evaluations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_id = Column(String, nullable=False)
    timestamp = Column(DateTime, default=utcnow, nullable=False)
    scope_id = Column(String, nullable=False)
    value = Column(Float, nullable=False)
    breached = Column(Boolean, nullable=False)
    action = Column(String, nullable=True)  # 'opened' | 'updated' | 'cleared' | 'skipped_cooldown'

    __table_args__ = (
        {"sqlite_autoincrement": True},
    )


class NotificationRetry(Base):
    """Notification retry queue for failed notifications"""
    __tablename__ = "notification_retries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_id = Column(String, ForeignKey("alerts_v2.id", ondelete="CASCADE"), nullable=False)
    rule_id = Column(String, nullable=True)
    attempt_count = Column(Integer, default=0)
    last_attempt_at = Column(DateTime, nullable=True)
    next_retry_at = Column(DateTime, nullable=False)
    channel_ids_json = Column(Text, nullable=False)  # JSON array of failed channel IDs
    created_at = Column(DateTime, default=utcnow, nullable=False)
    error_message = Column(Text, nullable=True)

    # Indexes
    __table_args__ = (
        Index('idx_notification_retry_next', 'next_retry_at'),  # Find retries to process
        {"sqlite_autoincrement": True},
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
    timestamp = Column(DateTime, default=utcnow, nullable=False)

    # Indexes for efficient queries
    __table_args__ = (
        Index('idx_event_timestamp', 'timestamp'),  # Sort/filter by time
        Index('idx_event_category', 'category'),  # Filter by category
        Index('idx_event_severity', 'severity'),  # Filter by severity
        Index('idx_event_host_id', 'host_id'),  # Filter by host
        Index('idx_event_container_id', 'container_id'),  # Filter by container
        Index('idx_event_correlation', 'correlation_id'),  # Group related events
        {"sqlite_autoincrement": True},
    )


class Tag(Base):
    """Tag definitions - reusable tags with metadata"""
    __tablename__ = "tags"

    id = Column(String, primary_key=True)  # UUID
    name = Column(String, nullable=False, unique=True)
    color = Column(String, nullable=True)  # Hex color code (e.g., "#3b82f6")
    kind = Column(String, nullable=False, default='user')  # 'user' | 'system'
    created_at = Column(DateTime, default=utcnow, nullable=False)
    last_used_at = Column(DateTime, nullable=True)  # Last time tag was assigned to something

    # Relationships
    assignments = relationship("TagAssignment", back_populates="tag", cascade="all, delete-orphan")


class TagAssignment(Base):
    """Tag assignments - links tags to entities (hosts, containers, groups)"""
    __tablename__ = "tag_assignments"

    tag_id = Column(String, ForeignKey("tags.id", ondelete="CASCADE"), nullable=False, primary_key=True)
    subject_type = Column(String, nullable=False, primary_key=True)  # 'host' | 'container' | 'group'
    subject_id = Column(String, nullable=False, primary_key=True)  # FK to hosts/containers

    # Logical identity fields for sticky behavior (container rebuilds)
    compose_project = Column(String, nullable=True)
    compose_service = Column(String, nullable=True)
    host_id_at_attach = Column(String, nullable=True)
    container_name_at_attach = Column(String, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=utcnow, nullable=False)
    last_seen_at = Column(DateTime, nullable=True)

    # Relationships
    tag = relationship("Tag", back_populates="assignments")

    # Indexes for efficient lookups
    __table_args__ = (
        Index('idx_tag_assignment_subject', 'subject_type', 'subject_id'),  # Lookup tags for a host/container
        Index('idx_tag_assignment_sticky', 'compose_project', 'compose_service', 'host_id_at_attach'),  # Sticky tag matching
        {"sqlite_autoincrement": False},
    )


class DatabaseManager:
    """
    Database management and operations (Singleton)

    ARCHITECTURE:
    This class uses the singleton pattern to ensure only ONE instance exists per process.
    Multiple instantiations will return the same instance, preventing:
    - Resource waste (multiple SQLAlchemy engines/connection pools)
    - Migration conflicts (Alembic running multiple times)
    - State inconsistency (different instances with different data)

    Thread-safe: Uses threading.Lock to prevent race conditions during initialization.
    """

    def __new__(cls, db_path: str = "data/dockmon.db"):
        """
        Singleton implementation using __new__.

        Returns the existing instance if one exists, otherwise creates it.
        Thread-safe using a lock to prevent race conditions.
        """
        global _database_manager_instance, _database_manager_lock

        # Fast path: instance already exists
        if _database_manager_instance is not None:
            # Verify db_path matches (warn if different)
            if _database_manager_instance.db_path != db_path:
                logger.warning(
                    f"DatabaseManager singleton already exists with path "
                    f"'{_database_manager_instance.db_path}', ignoring requested path '{db_path}'"
                )
            return _database_manager_instance

        # Slow path: need to create instance (use lock for thread safety)
        with _database_manager_lock:
            # Double-check pattern: another thread might have created it while we waited
            if _database_manager_instance is not None:
                return _database_manager_instance

            # Create the singleton instance
            instance = super(DatabaseManager, cls).__new__(cls)
            _database_manager_instance = instance
            return instance

    def __init__(self, db_path: str = "data/dockmon.db"):
        """
        Initialize database connection (only runs once for singleton).

        Note: __init__ is called every time DatabaseManager() is instantiated,
        but we use a flag to ensure initialization only happens once.
        """
        # Skip if already initialized (singleton pattern)
        if hasattr(self, '_initialized'):
            return

        self.db_path = db_path
        self._initialized = True

        # Ensure data directory exists
        data_dir = os.path.dirname(db_path)
        os.makedirs(data_dir, exist_ok=True)

        # Set secure permissions on data directory (rwx for owner only)
        try:
            os.chmod(data_dir, 0o700)
            logger.info(f"Set secure permissions (700) on data directory: {data_dir}")
        except OSError as e:
            logger.warning(f"Could not set permissions on data directory {data_dir}: {e}")

        # Create engine with connection pooling and timeout protection
        # Note: SQLite doesn't support pool_timeout/pool_recycle, but timeout in connect_args works
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={
                "check_same_thread": False,
                "timeout": 20  # 20 second query timeout to prevent DoS
            },
            poolclass=StaticPool,
            echo=False
        )

        # Configure SQLite for production performance and safety
        self._configure_sqlite_pragmas()

        # Create session factory
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

        # Create tables if they don't exist
        Base.metadata.create_all(bind=self.engine)

        # Run database migrations
        self._run_migrations()

        # Create indexes for tag_assignments
        self._create_tag_indexes()

        # Create indexes for alerts v2
        self._create_alert_v2_indexes()

        # Set secure permissions on database file (rw for owner only)
        self._secure_database_file()

        # Initialize default settings if needed
        self._initialize_defaults()

    def _configure_sqlite_pragmas(self):
        """
        Configure SQLite PRAGMA statements for production performance and safety.

        SECURITY & PERFORMANCE:
        - WAL mode: Write-Ahead Logging for concurrent reads during writes
        - SYNCHRONOUS=NORMAL: Safe with WAL, faster than FULL
        - TEMP_STORE=MEMORY: Keep temp tables in RAM (faster, no disk I/O)
        - CACHE_SIZE=-64000: 64MB cache (negative = KB, default is 2MB)
        """
        try:
            with self.engine.connect() as conn:
                # Enable Write-Ahead Logging (concurrent reads + writes)
                conn.execute(text("PRAGMA journal_mode=WAL"))

                # Balanced safety/performance (safe with WAL mode)
                conn.execute(text("PRAGMA synchronous=NORMAL"))

                # Store temp tables/indexes in memory (faster)
                conn.execute(text("PRAGMA temp_store=MEMORY"))

                # 64MB cache size (improves query performance)
                conn.execute(text("PRAGMA cache_size=-64000"))

                # Foreign key constraints enforcement (data integrity)
                conn.execute(text("PRAGMA foreign_keys=ON"))

                conn.commit()

            logger.info("SQLite PRAGMA configuration applied successfully (WAL mode, 64MB cache)")
        except Exception as e:
            logger.error(f"Failed to configure SQLite PRAGMAs: {e}", exc_info=True)
            # Non-fatal: SQLite will work with defaults

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
                    logger.info(f"Migrated {len(hosts_without_security_status)} hosts with security status")

                # Migration: Add event_sort_order column to users table if it doesn't exist
                inspector = session.connection().engine.dialect.get_columns(session.connection(), 'users')
                column_names = [col.get('name', '') for col in inspector if 'name' in col]

                if 'event_sort_order' not in column_names:
                    # Add the column using raw SQL
                    session.execute(text("ALTER TABLE users ADD COLUMN event_sort_order VARCHAR DEFAULT 'desc'"))
                    session.commit()
                    logger.info("Added event_sort_order column to users table")

                # Migration: Add container_sort_order column to users table if it doesn't exist
                if 'container_sort_order' not in column_names:
                    # Add the column using raw SQL
                    session.execute(text("ALTER TABLE users ADD COLUMN container_sort_order VARCHAR DEFAULT 'name-asc'"))
                    session.commit()
                    logger.info("Added container_sort_order column to users table")

                # Migration: Add modal_preferences column to users table if it doesn't exist
                if 'modal_preferences' not in column_names:
                    # Add the column using raw SQL
                    session.execute(text("ALTER TABLE users ADD COLUMN modal_preferences TEXT"))
                    session.commit()
                    logger.info("Added modal_preferences column to users table")

                # Migration: Add view_mode column to users table if it doesn't exist (Phase 4)
                if 'view_mode' not in column_names:
                    # Add the column using raw SQL
                    session.execute(text("ALTER TABLE users ADD COLUMN view_mode VARCHAR"))
                    session.commit()
                    logger.info("Added view_mode column to users table")

                # Migration: Add OS info columns to docker_hosts table (Phase 5)
                hosts_inspector = session.connection().engine.dialect.get_columns(session.connection(), 'docker_hosts')
                hosts_column_names = [col.get('name', '') for col in hosts_inspector if 'name' in col]

                if 'os_type' not in hosts_column_names:
                    session.execute(text("ALTER TABLE docker_hosts ADD COLUMN os_type TEXT"))
                    session.commit()
                    logger.info("Added os_type column to docker_hosts table")

                if 'os_version' not in hosts_column_names:
                    session.execute(text("ALTER TABLE docker_hosts ADD COLUMN os_version TEXT"))
                    session.commit()
                    logger.info("Added os_version column to docker_hosts table")

                if 'kernel_version' not in hosts_column_names:
                    session.execute(text("ALTER TABLE docker_hosts ADD COLUMN kernel_version TEXT"))
                    session.commit()
                    logger.info("Added kernel_version column to docker_hosts table")

                if 'docker_version' not in hosts_column_names:
                    session.execute(text("ALTER TABLE docker_hosts ADD COLUMN docker_version TEXT"))
                    session.commit()
                    logger.info("Added docker_version column to docker_hosts table")

                if 'daemon_started_at' not in hosts_column_names:
                    session.execute(text("ALTER TABLE docker_hosts ADD COLUMN daemon_started_at TEXT"))
                    session.commit()
                    logger.info("Added daemon_started_at column to docker_hosts table")

                # Migration: Add show_host_stats and show_container_stats columns to global_settings table
                settings_inspector = session.connection().engine.dialect.get_columns(session.connection(), 'global_settings')
                settings_column_names = [col['name'] for col in settings_inspector]

                if 'show_host_stats' not in settings_column_names:
                    session.execute(text("ALTER TABLE global_settings ADD COLUMN show_host_stats BOOLEAN DEFAULT 1"))
                    session.commit()
                    logger.info("Added show_host_stats column to global_settings table")

                if 'show_container_stats' not in settings_column_names:
                    session.execute(text("ALTER TABLE global_settings ADD COLUMN show_container_stats BOOLEAN DEFAULT 1"))
                    session.commit()
                    logger.info("Added show_container_stats column to global_settings table")

                # Migration: Add alert template category columns to global_settings table
                if 'alert_template_metric' not in settings_column_names:
                    session.execute(text("ALTER TABLE global_settings ADD COLUMN alert_template_metric TEXT"))
                    session.commit()
                    logger.info("Added alert_template_metric column to global_settings table")

                if 'alert_template_state_change' not in settings_column_names:
                    session.execute(text("ALTER TABLE global_settings ADD COLUMN alert_template_state_change TEXT"))
                    session.commit()
                    logger.info("Added alert_template_state_change column to global_settings table")

                if 'alert_template_health' not in settings_column_names:
                    session.execute(text("ALTER TABLE global_settings ADD COLUMN alert_template_health TEXT"))
                    session.commit()
                    logger.info("Added alert_template_health column to global_settings table")

                if 'alert_template_update' not in settings_column_names:
                    session.execute(text("ALTER TABLE global_settings ADD COLUMN alert_template_update TEXT"))
                    session.commit()
                    logger.info("Added alert_template_update column to global_settings table")

                # Migration: Drop deprecated container_history table
                # This table has been replaced by the EventLog table
                inspector_result = session.connection().engine.dialect.get_table_names(session.connection())
                if 'container_history' in inspector_result:
                    session.execute(text("DROP TABLE container_history"))
                    session.commit()
                    logger.info("Dropped deprecated container_history table (replaced by EventLog)")

                # Migration: Add polling_interval_migrated column if it doesn't exist
                if 'polling_interval_migrated' not in settings_column_names:
                    session.execute(text("ALTER TABLE global_settings ADD COLUMN polling_interval_migrated BOOLEAN DEFAULT 0"))
                    session.commit()
                    logger.info("Added polling_interval_migrated column to global_settings table")

                # Migration: Update polling_interval to 2 seconds (only once, on first startup after this update)
                settings = session.query(GlobalSettings).first()
                if settings and not settings.polling_interval_migrated:
                    # Only update if the user hasn't customized it (still at old default of 5 or 10)
                    if settings.polling_interval >= 5:
                        settings.polling_interval = 2
                        settings.polling_interval_migrated = True
                        session.commit()
                        logger.info("Migrated polling_interval to 2 seconds (from previous default)")
                    else:
                        # User has already customized to something < 5, just mark as migrated
                        settings.polling_interval_migrated = True
                        session.commit()

                # Migration: Add custom_template column to alert_rules_v2 table
                alert_rules_inspector = session.connection().engine.dialect.get_columns(session.connection(), 'alert_rules_v2')
                alert_rules_column_names = [col['name'] for col in alert_rules_inspector]

                if 'custom_template' not in alert_rules_column_names:
                    session.execute(text("ALTER TABLE alert_rules_v2 ADD COLUMN custom_template TEXT"))
                    session.commit()
                    logger.info("Added custom_template column to alert_rules_v2 table")

                # Migration: Clear old tag data (starting fresh with normalized schema)
                # The new tag system uses 'tags' and 'tag_assignments' tables
                table_names = session.connection().engine.dialect.get_table_names(session.connection())
                if 'tags' in table_names and 'tag_assignments' in table_names:
                    # Clear old host tags (JSON array format - deprecated)
                    session.execute(text("UPDATE docker_hosts SET tags = NULL WHERE tags IS NOT NULL"))

                    # Clear old container tags (CSV format - deprecated)
                    session.execute(text("UPDATE container_desired_states SET custom_tags = NULL WHERE custom_tags IS NOT NULL"))

                    session.commit()
                    logger.info("Cleared legacy tag data - starting fresh with normalized schema")

        except Exception as e:
            logger.info(f"Migration warning: {e}")
            # Don't fail startup on migration errors

    def _create_tag_indexes(self):
        """Create indexes for tag_assignments table for efficient queries"""
        try:
            with self.get_session() as session:
                # Check if indexes already exist
                inspector = session.connection().engine.dialect.get_indexes(session.connection(), 'tag_assignments')
                existing_indexes = [idx['name'] for idx in inspector]

                # Create index for subject lookups (find all tags for a host/container)
                if 'idx_tag_assignments_subject' not in existing_indexes:
                    session.execute(text(
                        "CREATE INDEX IF NOT EXISTS idx_tag_assignments_subject "
                        "ON tag_assignments(subject_type, subject_id)"
                    ))
                    logger.info("Created index idx_tag_assignments_subject")

                # Create index for compose/logical identity matching (sticky tags)
                if 'idx_tag_assignments_compose' not in existing_indexes:
                    session.execute(text(
                        "CREATE INDEX IF NOT EXISTS idx_tag_assignments_compose "
                        "ON tag_assignments(compose_project, compose_service, host_id_at_attach)"
                    ))
                    logger.info("Created index idx_tag_assignments_compose")

                # Create index for tag_id lookups (find all entities with a specific tag)
                if 'idx_tag_assignments_tag_id' not in existing_indexes:
                    session.execute(text(
                        "CREATE INDEX IF NOT EXISTS idx_tag_assignments_tag_id "
                        "ON tag_assignments(tag_id)"
                    ))
                    logger.info("Created index idx_tag_assignments_tag_id")

                session.commit()

        except Exception as e:
            logger.warning(f"Failed to create tag indexes: {e}")
            # Don't fail startup on index creation errors

    def _create_alert_v2_indexes(self):
        """Create composite indexes for alerts v2 tables for optimal query performance"""
        try:
            with self.get_session() as session:
                # Composite index for "show me open/snoozed alerts for this host/container"
                session.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_alerts_v2_scope_state "
                    "ON alerts_v2(scope_type, scope_id, state, last_seen DESC)"
                ))

                # Index for dashboard KPI counting
                session.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_alerts_v2_state_last_seen "
                    "ON alerts_v2(state, last_seen DESC)"
                ))

                # Index for rule lookups
                session.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_alerts_v2_rule_id "
                    "ON alerts_v2(rule_id)"
                ))

                # Index for enabled rule lookups
                session.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_alert_rules_v2_enabled "
                    "ON alert_rules_v2(enabled)"
                ))

                # Index for rule evaluation history queries
                session.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_rule_evaluations_rule_time "
                    "ON rule_evaluations(rule_id, timestamp DESC)"
                ))

                # Index for evaluation history scope queries
                session.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_rule_evaluations_scope_time "
                    "ON rule_evaluations(scope_id, timestamp DESC)"
                ))

                # Index for event_logs timestamp queries (date range filtering)
                session.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_event_logs_timestamp "
                    "ON event_logs(timestamp DESC)"
                ))

                # Index for event_logs correlation_id queries (event correlation)
                session.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_event_logs_correlation_id "
                    "ON event_logs(correlation_id)"
                ))

                # Composite index for scope queries (host_id + container_id filtering)
                session.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_event_logs_scope "
                    "ON event_logs(host_id, container_id, timestamp DESC)"
                ))

                session.commit()
                logger.info("Created alert v2 and event_logs composite indexes for optimal query performance")

        except Exception as e:
            logger.warning(f"Failed to create alert v2 indexes: {e}")
            # Don't fail startup on index creation errors

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
            try:
                host = DockerHostDB(**host_data)
                session.add(host)
                session.commit()
                session.refresh(host)
                logger.info(f"Added host {host.name} ({host.id[:8]}) to database")
                return host
            except Exception as e:
                logger.error(f"Failed to add host to database: {e}")
                raise

    def get_hosts(self, active_only: bool = True) -> List[DockerHostDB]:
        """Get all Docker hosts ordered by creation time"""
        with self.get_session() as session:
            query = session.query(DockerHostDB)
            if active_only:
                query = query.filter(DockerHostDB.is_active == True)
            # Order by created_at to ensure consistent ordering (oldest first)
            query = query.order_by(DockerHostDB.created_at)
            # Add safety limit to prevent memory exhaustion with large host lists
            return query.limit(1000).all()

    def get_host(self, host_id: str) -> Optional[DockerHostDB]:
        """Get a specific Docker host"""
        with self.get_session() as session:
            return session.query(DockerHostDB).filter(DockerHostDB.id == host_id).first()

    def update_host(self, host_id: str, updates: dict) -> Optional[DockerHostDB]:
        """Update a Docker host"""
        with self.get_session() as session:
            try:
                host = session.query(DockerHostDB).filter(DockerHostDB.id == host_id).first()
                if host:
                    for key, value in updates.items():
                        setattr(host, key, value)
                    host.updated_at = datetime.now(timezone.utc)
                    session.commit()
                    session.refresh(host)
                    logger.info(f"Updated host {host.name} ({host_id[:8]}) in database")
                return host
            except Exception as e:
                logger.error(f"Failed to update host {host_id[:8]} in database: {e}")
                raise

    def cleanup_host_data(self, session, host_id: str, host_name: str) -> dict:
        """
        Central cleanup function for all host-related data.
        Called when deleting a host to ensure all foreign key constraints are satisfied.

        Returns a dict with counts of what was cleaned up for logging.

        Design Philosophy:
        - DELETE: Host-specific settings (AutoRestartConfig, ContainerDesiredState)
        - CLOSE: Active alerts (resolve AlertV2 instances)
        - UPDATE: Alert rules (remove containers from this host)
        - KEEP: Audit logs (EventLog records preserve history)

        When adding new tables with host_id foreign keys:
        1. Add cleanup logic here
        2. Add to the returned counts dict
        3. Add appropriate logging
        """
        cleanup_stats = {}

        logger.info(f"Starting cleanup for host {host_name} ({host_id[:8]})...")

        # 1. Delete AutoRestartConfig records for this host
        # These are host-specific settings that don't make sense without the host
        auto_restart_count = session.query(AutoRestartConfig).filter(
            AutoRestartConfig.host_id == host_id
        ).delete(synchronize_session=False)
        cleanup_stats['auto_restart_configs'] = auto_restart_count
        if auto_restart_count > 0:
            logger.info(f"  ✓ Deleted {auto_restart_count} auto-restart config(s)")

        # 2. Delete ContainerDesiredState records for this host
        # These are host-specific settings that don't make sense without the host
        desired_state_count = session.query(ContainerDesiredState).filter(
            ContainerDesiredState.host_id == host_id
        ).delete(synchronize_session=False)
        cleanup_stats['desired_states'] = desired_state_count
        if desired_state_count > 0:
            logger.info(f"  ✓ Deleted {desired_state_count} container desired state(s)")

        # 3. Resolve/close all active AlertV2 instances for this host
        # Active alerts for a deleted host should be auto-resolved
        # AlertV2 doesn't have host_id - it has scope_type and scope_id
        # AlertV2 also doesn't have updated_at - only first_seen, last_seen
        alerts_updated = session.query(AlertV2).filter(
            AlertV2.scope_type == 'host',
            AlertV2.scope_id == host_id,
            AlertV2.state == 'open'
        ).update({
            'state': 'resolved',
            'resolved_at': datetime.now(timezone.utc)
        }, synchronize_session=False)
        cleanup_stats['alerts_resolved'] = alerts_updated
        if alerts_updated > 0:
            logger.info(f"  ✓ Resolved {alerts_updated} open alert(s)")

        # 4. Keep EventLog records (for audit trail)
        # Events preserve historical data and show the original host_name
        event_count = session.query(EventLog).filter(EventLog.host_id == host_id).count()
        cleanup_stats['events_kept'] = event_count
        if event_count > 0:
            logger.info(f"  ✓ Keeping {event_count} event log entries for audit trail")

        # TODO: Add cleanup for any new tables with host_id foreign keys here
        # Example:
        # new_table_count = session.query(NewTable).filter(NewTable.host_id == host_id).delete()
        # cleanup_stats['new_table_records'] = new_table_count

        return cleanup_stats

    def delete_host(self, host_id: str) -> bool:
        """Delete a Docker host and clean up all related data"""
        with self.get_session() as session:
            try:
                host = session.query(DockerHostDB).filter(DockerHostDB.id == host_id).first()
                if not host:
                    logger.warning(f"Attempted to delete non-existent host {host_id[:8]}")
                    return False

                host_name = host.name
                logger.info(f"Deleting host {host_name} ({host_id[:8]})...")

                # Run centralized cleanup
                cleanup_stats = self.cleanup_host_data(session, host_id, host_name)

                # Delete the host itself
                session.delete(host)
                session.commit()

                logger.info(f"Successfully deleted host {host_name} ({host_id[:8]})")
                logger.info(f"Cleanup summary: {cleanup_stats}")
                return True
            except Exception as e:
                session.rollback()
                logger.error(f"Failed to delete host {host_id[:8]} from database: {e}")
                raise

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
            try:
                config = session.query(AutoRestartConfig).filter(
                    AutoRestartConfig.host_id == host_id,
                    AutoRestartConfig.container_id == container_id
                ).first()

                if config:
                    config.enabled = enabled
                    config.updated_at = datetime.now(timezone.utc)
                    if not enabled:
                        config.restart_count = 0
                    logger.info(f"Updated auto-restart for {container_name} ({container_id[:12]}): enabled={enabled}")
                else:
                    config = AutoRestartConfig(
                        host_id=host_id,
                        container_id=container_id,
                        container_name=container_name,
                        enabled=enabled
                    )
                    session.add(config)
                    logger.info(f"Created auto-restart config for {container_name} ({container_id[:12]}): enabled={enabled}")

                session.commit()
            except Exception as e:
                logger.error(f"Failed to set auto-restart for {container_id[:12]}: {e}")
                raise

    def increment_restart_count(self, host_id: str, container_id: str):
        """Increment restart count for a container"""
        with self.get_session() as session:
            try:
                config = session.query(AutoRestartConfig).filter(
                    AutoRestartConfig.host_id == host_id,
                    AutoRestartConfig.container_id == container_id
                ).first()

                if config:
                    config.restart_count += 1
                    config.last_restart = datetime.now(timezone.utc)
                    session.commit()
                    logger.debug(f"Incremented restart count for {container_id[:12]} to {config.restart_count}")
            except Exception as e:
                logger.error(f"Failed to increment restart count for {container_id[:12]}: {e}")
                raise

    def reset_restart_count(self, host_id: str, container_id: str):
        """Reset restart count for a container"""
        with self.get_session() as session:
            try:
                config = session.query(AutoRestartConfig).filter(
                    AutoRestartConfig.host_id == host_id,
                    AutoRestartConfig.container_id == container_id
                ).first()

                if config:
                    config.restart_count = 0
                    session.commit()
                    logger.debug(f"Reset restart count for {container_id[:12]}")
            except Exception as e:
                logger.error(f"Failed to reset restart count for {container_id[:12]}: {e}")
                raise

    # Container Desired State Operations
    def get_desired_state(self, host_id: str, container_id: str) -> tuple[str, Optional[str]]:
        """Get desired state and web UI URL for a container

        Returns:
            tuple: (desired_state, web_ui_url)
        """
        with self.get_session() as session:
            config = session.query(ContainerDesiredState).filter(
                ContainerDesiredState.host_id == host_id,
                ContainerDesiredState.container_id == container_id
            ).first()
            if config:
                return (config.desired_state, config.web_ui_url)
            return ('unspecified', None)

    def set_desired_state(self, host_id: str, container_id: str, container_name: str, desired_state: str, web_ui_url: str = None):
        """Set desired state for a container"""
        with self.get_session() as session:
            try:
                config = session.query(ContainerDesiredState).filter(
                    ContainerDesiredState.host_id == host_id,
                    ContainerDesiredState.container_id == container_id
                ).first()

                if config:
                    config.desired_state = desired_state
                    config.web_ui_url = web_ui_url
                    config.updated_at = datetime.now(timezone.utc)
                    logger.info(f"Updated desired state for {container_name} ({container_id[:12]}): {desired_state}")
                else:
                    config = ContainerDesiredState(
                        host_id=host_id,
                        container_id=container_id,
                        container_name=container_name,
                        desired_state=desired_state,
                        web_ui_url=web_ui_url
                    )
                    session.add(config)
                    logger.info(f"Created desired state config for {container_name} ({container_id[:12]}): {desired_state}")

                session.commit()
            except Exception as e:
                logger.error(f"Failed to set desired state for {container_id[:12]}: {e}")
                raise

    # Container Auto-Update Operations
    def set_container_auto_update(self, container_key: str, enabled: bool, floating_tag_mode: str = 'exact'):
        """Enable/disable auto-update for a container with tracking mode

        Args:
            container_key: Composite key format "host_id:container_id"
            enabled: Whether to enable auto-updates
            floating_tag_mode: Update tracking mode (exact|minor|major|latest)
        """
        with self.get_session() as session:
            try:
                config = session.query(ContainerUpdate).filter(
                    ContainerUpdate.container_id == container_key
                ).first()

                if config:
                    config.auto_update_enabled = enabled
                    config.floating_tag_mode = floating_tag_mode
                    config.updated_at = datetime.now(timezone.utc)
                    logger.info(f"Updated auto-update for {container_key}: enabled={enabled}, mode={floating_tag_mode}")
                else:
                    # Create new ContainerUpdate record if it doesn't exist
                    # Extract host_id from composite key
                    host_id = container_key.split(':')[0] if ':' in container_key else ''

                    config = ContainerUpdate(
                        container_id=container_key,
                        host_id=host_id,
                        current_image='',  # Will be populated by update checker
                        current_digest='',
                        auto_update_enabled=enabled,
                        floating_tag_mode=floating_tag_mode
                    )
                    session.add(config)
                    logger.info(f"Created auto-update config for {container_key}: enabled={enabled}, mode={floating_tag_mode}")

                session.commit()
            except Exception as e:
                logger.error(f"Failed to set auto-update for {container_key}: {e}")
                raise

    # ===========================
    # TAG OPERATIONS (Normalized Schema)
    # ===========================

    @staticmethod
    def _validate_tag_name(tag_name: str) -> str:
        """Validate and sanitize tag name"""
        if not tag_name or not isinstance(tag_name, str):
            raise ValueError("Tag name must be a non-empty string")

        tag_name = tag_name.strip().lower()

        if len(tag_name) == 0:
            raise ValueError("Tag name cannot be empty")
        if len(tag_name) > 100:
            raise ValueError("Tag name too long (max 100 characters)")
        if not tag_name.replace('-', '').replace('_', '').replace(':', '').isalnum():
            raise ValueError("Tag name can only contain alphanumeric characters, hyphens, underscores, and colons")

        return tag_name

    @staticmethod
    def _validate_color(color: str = None) -> str:
        """Validate hex color format"""
        if color is None:
            return None

        if not isinstance(color, str):
            raise ValueError("Color must be a string")

        color = color.strip()

        # Allow both #RRGGBB and RRGGBB formats
        if color.startswith('#'):
            color = color[1:]

        if len(color) != 6:
            raise ValueError("Color must be 6-character hex code")

        try:
            int(color, 16)
        except ValueError:
            raise ValueError("Color must be valid hex code")

        return f"#{color}"

    @staticmethod
    def _validate_subject_type(subject_type: str) -> str:
        """Validate subject type"""
        valid_types = ['host', 'container', 'group']
        if subject_type not in valid_types:
            raise ValueError(f"Subject type must be one of: {', '.join(valid_types)}")
        return subject_type

    def get_or_create_tag(self, tag_name: str, kind: str = 'user', color: str = None) -> Tag:
        """Get existing tag or create new one"""
        tag_name = self._validate_tag_name(tag_name)
        color = self._validate_color(color)

        with self.get_session() as session:
            tag = session.query(Tag).filter(Tag.name == tag_name).first()

            if not tag:
                tag = Tag(
                    id=str(uuid.uuid4()),
                    name=tag_name,
                    kind=kind,
                    color=color
                )
                session.add(tag)
                session.commit()
                session.refresh(tag)
                logger.info(f"Created new tag: {tag_name}")

            return tag

    def assign_tag_to_subject(
        self,
        tag_name: str,
        subject_type: str,
        subject_id: str,
        compose_project: str = None,
        compose_service: str = None,
        host_id_at_attach: str = None,
        container_name_at_attach: str = None
    ) -> TagAssignment:
        """Assign a tag to a subject (host, container, group)"""
        subject_type = self._validate_subject_type(subject_type)

        with self.get_session() as session:
            # Get or create tag (validates tag_name internally)
            tag = self.get_or_create_tag(tag_name)

            # Update tag's last_used_at timestamp
            tag_obj = session.query(Tag).filter(Tag.id == tag.id).first()
            if tag_obj:
                tag_obj.last_used_at = datetime.now(timezone.utc)

            # Check if assignment already exists
            existing = session.query(TagAssignment).filter(
                TagAssignment.tag_id == tag.id,
                TagAssignment.subject_type == subject_type,
                TagAssignment.subject_id == subject_id
            ).first()

            if existing:
                # Update last_seen_at
                existing.last_seen_at = datetime.now(timezone.utc)
                session.commit()
                return existing

            # Create new assignment
            assignment = TagAssignment(
                tag_id=tag.id,
                subject_type=subject_type,
                subject_id=subject_id,
                compose_project=compose_project,
                compose_service=compose_service,
                host_id_at_attach=host_id_at_attach,
                container_name_at_attach=container_name_at_attach,
                last_seen_at=datetime.now(timezone.utc)
            )
            session.add(assignment)
            session.commit()
            logger.info(f"Assigned tag '{tag_name}' to {subject_type}:{subject_id}")
            return assignment

    def remove_tag_from_subject(self, tag_name: str, subject_type: str, subject_id: str) -> bool:
        """Remove a tag assignment from a subject"""
        tag_name = self._validate_tag_name(tag_name)
        subject_type = self._validate_subject_type(subject_type)

        with self.get_session() as session:
            tag = session.query(Tag).filter(Tag.name == tag_name).first()

            if not tag:
                return False

            assignment = session.query(TagAssignment).filter(
                TagAssignment.tag_id == tag.id,
                TagAssignment.subject_type == subject_type,
                TagAssignment.subject_id == subject_id
            ).first()

            if assignment:
                session.delete(assignment)
                session.commit()
                logger.info(f"Removed tag '{tag_name}' from {subject_type}:{subject_id}")
                return True

            return False

    def get_tags_for_subject(self, subject_type: str, subject_id: str) -> list[str]:
        """Get all tag names for a subject (optimized with JOIN to avoid N+1)"""
        subject_type = self._validate_subject_type(subject_type)

        with self.get_session() as session:
            # Use JOIN to fetch tags in a single query (avoids N+1)
            tag_names = session.query(Tag.name).join(
                TagAssignment,
                TagAssignment.tag_id == Tag.id
            ).filter(
                TagAssignment.subject_type == subject_type,
                TagAssignment.subject_id == subject_id
            ).all()

            return sorted([name[0] for name in tag_names])

    def get_subjects_with_tag(self, tag_name: str, subject_type: str = None) -> list[dict]:
        """Get all subjects that have a specific tag"""
        with self.get_session() as session:
            tag_name = tag_name.strip().lower()
            tag = session.query(Tag).filter(Tag.name == tag_name).first()

            if not tag:
                return []

            query = session.query(TagAssignment).filter(TagAssignment.tag_id == tag.id)

            if subject_type:
                query = query.filter(TagAssignment.subject_type == subject_type)

            assignments = query.all()

            return [
                {
                    'subject_type': a.subject_type,
                    'subject_id': a.subject_id,
                    'created_at': a.created_at.isoformat() + 'Z' if a.created_at else None,
                    'last_seen_at': a.last_seen_at.isoformat() + 'Z' if a.last_seen_at else None
                }
                for a in assignments
            ]

    def update_subject_tags(
        self,
        subject_type: str,
        subject_id: str,
        tags_to_add: list[str],
        tags_to_remove: list[str],
        **identity_fields
    ) -> list[str]:
        """Update tags for a subject (add and/or remove)"""
        subject_type = self._validate_subject_type(subject_type)

        # Limit number of tags per operation to prevent abuse
        MAX_TAGS_PER_OPERATION = 50
        if len(tags_to_add) > MAX_TAGS_PER_OPERATION:
            raise ValueError(f"Cannot add more than {MAX_TAGS_PER_OPERATION} tags at once")
        if len(tags_to_remove) > MAX_TAGS_PER_OPERATION:
            raise ValueError(f"Cannot remove more than {MAX_TAGS_PER_OPERATION} tags at once")

        with self.get_session() as session:
            try:
                # Remove tags
                for tag_name in tags_to_remove:
                    self.remove_tag_from_subject(tag_name, subject_type, subject_id)

                # Add tags
                for tag_name in tags_to_add:
                    self.assign_tag_to_subject(
                        tag_name,
                        subject_type,
                        subject_id,
                        **identity_fields
                    )

                # Return current tags
                current_tags = self.get_tags_for_subject(subject_type, subject_id)

                # Enforce maximum total tags per subject
                MAX_TAGS_PER_SUBJECT = 100
                if len(current_tags) > MAX_TAGS_PER_SUBJECT:
                    logger.warning(f"Subject {subject_type}:{subject_id} has {len(current_tags)} tags (max {MAX_TAGS_PER_SUBJECT})")

                return current_tags

            except Exception as e:
                logger.error(f"Failed to update tags for {subject_type}:{subject_id}: {e}")
                raise

    def get_all_tags_v2(self, query: str = "", limit: int = 100, subject_type: Optional[str] = None) -> list[dict]:
        """Get all tag definitions with metadata, optionally filtered by subject_type (host/container)"""
        with self.get_session() as session:
            tags_query = session.query(Tag)

            # Filter by subject_type if specified (get tags that are used on that type of subject)
            if subject_type:
                tags_query = tags_query.join(TagAssignment).filter(TagAssignment.subject_type == subject_type)
                tags_query = tags_query.distinct()

            if query:
                query_lower = query.lower()
                # Escape LIKE wildcards to prevent unintended pattern matching
                escaped_query = query_lower.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
                tags_query = tags_query.filter(Tag.name.like(f'%{escaped_query}%', escape='\\'))

            tags = tags_query.order_by(Tag.name).limit(limit).all()

            return [
                {
                    'id': tag.id,
                    'name': tag.name,
                    'color': tag.color,
                    'kind': tag.kind,
                    'created_at': tag.created_at.isoformat() + 'Z' if tag.created_at else None
                }
                for tag in tags
            ]

    def reattach_tags_for_container(
        self,
        host_id: str,
        container_id: str,
        container_name: str,
        compose_project: str = None,
        compose_service: str = None
    ) -> list[str]:
        """
        Reattach tags to a rebuilt container based on logical identity.
        This implements the "sticky tags" feature.
        """
        with self.get_session() as session:
            reattached_tags = []

            # Try to find previous assignments by compose identity
            if compose_project and compose_service:
                prev_assignments = session.query(TagAssignment).filter(
                    TagAssignment.subject_type == 'container',
                    TagAssignment.compose_project == compose_project,
                    TagAssignment.compose_service == compose_service,
                    TagAssignment.host_id_at_attach == host_id
                ).all()

                for prev_assignment in prev_assignments:
                    tag = session.query(Tag).filter(Tag.id == prev_assignment.tag_id).first()
                    if tag:
                        # Create new assignment for the new container ID
                        container_key = make_composite_key(host_id, container_id)

                        # Check if already assigned
                        existing = session.query(TagAssignment).filter(
                            TagAssignment.tag_id == tag.id,
                            TagAssignment.subject_type == 'container',
                            TagAssignment.subject_id == container_key
                        ).first()

                        if not existing:
                            new_assignment = TagAssignment(
                                tag_id=tag.id,
                                subject_type='container',
                                subject_id=container_key,
                                compose_project=compose_project,
                                compose_service=compose_service,
                                host_id_at_attach=host_id,
                                container_name_at_attach=container_name,
                                last_seen_at=datetime.now(timezone.utc)
                            )
                            session.add(new_assignment)
                            reattached_tags.append(tag.name)
                            logger.info(f"Reattached tag '{tag.name}' to container {container_name} via compose identity")

            # Fallback: try to match by container name + host
            if not reattached_tags:
                prev_assignments = session.query(TagAssignment).filter(
                    TagAssignment.subject_type == 'container',
                    TagAssignment.container_name_at_attach == container_name,
                    TagAssignment.host_id_at_attach == host_id
                ).all()

                for prev_assignment in prev_assignments:
                    tag = session.query(Tag).filter(Tag.id == prev_assignment.tag_id).first()
                    if tag:
                        container_key = make_composite_key(host_id, container_id)

                        existing = session.query(TagAssignment).filter(
                            TagAssignment.tag_id == tag.id,
                            TagAssignment.subject_type == 'container',
                            TagAssignment.subject_id == container_key
                        ).first()

                        if not existing:
                            new_assignment = TagAssignment(
                                tag_id=tag.id,
                                subject_type='container',
                                subject_id=container_key,
                                host_id_at_attach=host_id,
                                container_name_at_attach=container_name,
                                last_seen_at=datetime.now(timezone.utc)
                            )
                            session.add(new_assignment)
                            reattached_tags.append(tag.name)
                            logger.info(f"Reattached tag '{tag.name}' to container {container_name} via name match")

            if reattached_tags:
                session.commit()
                logger.info(f"Reattached {len(reattached_tags)} tags to {container_name}")

            return reattached_tags

    def cleanup_orphaned_tag_assignments(self, days_old: int = 30, batch_size: int = 1000) -> int:
        """
        Clean up tag assignments for containers/hosts that no longer exist.

        Args:
            days_old: Remove assignments not seen in this many days
            batch_size: Maximum number of assignments to delete in one batch

        Returns:
            Number of assignments removed
        """
        with self.get_session() as session:
            from datetime import timedelta
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_old)

            # Find orphaned container assignments (last_seen_at > cutoff)
            # Process in batches to avoid locking the database for too long
            total_deleted = 0
            while True:
                # Get batch of orphaned assignments
                assignments_to_delete = session.query(TagAssignment).filter(
                    TagAssignment.subject_type == 'container',
                    TagAssignment.last_seen_at < cutoff_date
                ).limit(batch_size).all()

                if not assignments_to_delete:
                    break

                # Delete this batch
                for assignment in assignments_to_delete:
                    session.delete(assignment)

                session.commit()
                batch_count = len(assignments_to_delete)
                total_deleted += batch_count

                logger.debug(f"Deleted batch of {batch_count} orphaned tag assignments")

                # If we deleted fewer than batch_size, we're done
                if batch_count < batch_size:
                    break

            if total_deleted > 0:
                logger.info(f"Cleaned up {total_deleted} orphaned tag assignments")

            return total_deleted

    def cleanup_unused_tags(self, days_unused: int = 30) -> int:
        """
        Clean up tags that have not been used (assigned to anything) for N days.

        A tag is considered unused if:
        1. It has no current assignments (assignment count = 0)
        2. Its last_used_at timestamp is older than days_unused

        Args:
            days_unused: Remove tags not used in this many days (0 = never delete)

        Returns:
            Number of tags removed
        """
        if days_unused <= 0:
            return 0  # If set to 0, never delete unused tags

        with self.get_session() as session:
            from datetime import timedelta
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_unused)

            # Find tags with no assignments and not used recently
            tags_to_delete = session.query(Tag).outerjoin(TagAssignment).group_by(Tag.id).having(
                func.count(TagAssignment.tag_id) == 0
            ).filter(
                Tag.last_used_at < cutoff_date
            ).limit(1000).all()  # Add safety limit to prevent memory exhaustion

            deleted_count = 0
            for tag in tags_to_delete:
                session.delete(tag)
                deleted_count += 1
                logger.info(f"Deleted unused tag '{tag.name}' (last used: {tag.last_used_at})")

            if deleted_count > 0:
                session.commit()
                logger.info(f"Cleaned up {deleted_count} unused tags not used in {days_unused} days")

            return deleted_count

    # Global Settings
    def get_settings(self) -> GlobalSettings:
        """Get global settings"""
        with self.get_session() as session:
            return session.query(GlobalSettings).first()

    def update_settings(self, updates: dict) -> GlobalSettings:
        """
        Update global settings

        NOTE: Input should already be validated by Pydantic at API layer.
        This method adds defense-in-depth checks.
        """
        with self.get_session() as session:
            try:
                settings = session.query(GlobalSettings).first()

                # Whitelist of allowed setting keys (defense in depth)
                ALLOWED_SETTINGS = {
                    'max_retries', 'retry_delay', 'default_auto_restart',
                    'polling_interval', 'connection_timeout', 'event_retention_days',
                    'alert_retention_days', 'unused_tag_retention_days',
                    'enable_notifications', 'alert_template', 'alert_template_metric',
                    'alert_template_state_change', 'alert_template_health', 'alert_template_update',
                    'blackout_windows', 'timezone_offset', 'show_host_stats',
                    'show_container_stats', 'show_container_alerts_on_hosts',
                    'auto_update_enabled_default', 'update_check_interval_hours',
                    'update_check_time', 'skip_compose_containers', 'health_check_timeout_seconds'
                }

                for key, value in updates.items():
                    # Check 1: Key must be in whitelist
                    if key not in ALLOWED_SETTINGS:
                        logger.warning(f"Rejected unknown setting key: {key}")
                        continue

                    # Check 2: Attribute must exist on model
                    if not hasattr(settings, key):
                        logger.error(f"Setting key '{key}' not found on GlobalSettings model")
                        continue

                    # Check 3: Type safety (runtime check as backup)
                    expected_type = type(getattr(settings, key))
                    if expected_type is not type(None) and value is not None:
                        if not isinstance(value, expected_type):
                            logger.error(
                                f"Type mismatch for '{key}': expected {expected_type.__name__}, "
                                f"got {type(value).__name__}. Skipping."
                            )
                            continue

                    # All checks passed - apply update
                    setattr(settings, key, value)
                    logger.debug(f"Updated setting: {key} = {value}")

                settings.updated_at = datetime.now(timezone.utc)
                session.commit()
                session.refresh(settings)
                # Expunge the object so it's not tied to the session
                session.expunge(settings)

                logger.info(f"Updated {len(updates)} settings successfully")
                return settings

            except Exception as e:
                logger.error(f"Failed to update global settings: {e}", exc_info=True)
                raise Exception("Database operation failed")

    # Notification Channels
    def add_notification_channel(self, channel_data: dict) -> NotificationChannel:
        """Add a notification channel"""
        with self.get_session() as session:
            try:
                channel = NotificationChannel(**channel_data)
                session.add(channel)
                session.commit()
                session.refresh(channel)
                logger.info(f"Added notification channel: {channel.name} (type: {channel.type})")
                return channel
            except Exception as e:
                logger.error(f"Failed to add notification channel: {e}")
                raise

    def get_notification_channels(self, enabled_only: bool = True) -> List[NotificationChannel]:
        """Get all notification channels"""
        with self.get_session() as session:
            query = session.query(NotificationChannel)
            if enabled_only:
                query = query.filter(NotificationChannel.enabled == True)
            return query.all()

    # V1 method get_notification_channels_by_ids() removed - unused by V2

    def update_notification_channel(self, channel_id: int, updates: dict) -> Optional[NotificationChannel]:
        """Update a notification channel"""
        with self.get_session() as session:
            try:
                channel = session.query(NotificationChannel).filter(NotificationChannel.id == channel_id).first()
                if channel:
                    for key, value in updates.items():
                        setattr(channel, key, value)
                    channel.updated_at = datetime.now(timezone.utc)
                    session.commit()
                    session.refresh(channel)
                    logger.info(f"Updated notification channel: {channel.name} (ID: {channel_id})")
                return channel
            except Exception as e:
                logger.error(f"Failed to update notification channel {channel_id}: {e}")
                raise

    def delete_notification_channel(self, channel_id: int) -> bool:
        """Delete a notification channel"""
        with self.get_session() as session:
            try:
                channel = session.query(NotificationChannel).filter(NotificationChannel.id == channel_id).first()
                if channel:
                    channel_name = channel.name
                    session.delete(channel)
                    session.commit()
                    logger.info(f"Deleted notification channel: {channel_name} (ID: {channel_id})")
                    return True
                logger.warning(f"Attempted to delete non-existent notification channel {channel_id}")
                return False
            except Exception as e:
                logger.error(f"Failed to delete notification channel {channel_id}: {e}")
                raise

    # V1 Alert Rules methods removed: add_alert_rule, get_alert_rule, get_alert_rules,
    # update_alert_rule, delete_alert_rule
    # V1 alert system has been removed - V2 uses AlertRuleV2 and AlertEngine

    # ==================== Alert Rules V2 Methods ====================

    def get_alert_rules_v2(self, enabled_only: bool = False) -> List[AlertRuleV2]:
        """Get all alert rules v2"""
        with self.get_session() as session:
            query = session.query(AlertRuleV2)
            if enabled_only:
                query = query.filter(AlertRuleV2.enabled == True)
            return query.all()

    def get_alert_rule_v2(self, rule_id: str) -> Optional[AlertRuleV2]:
        """Get a single alert rule v2 by ID"""
        with self.get_session() as session:
            return session.query(AlertRuleV2).filter(AlertRuleV2.id == rule_id).first()

    def get_or_create_system_alert_rule(self) -> AlertRuleV2:
        """
        Get or create the system alert rule for alerting on internal failures.

        This rule is auto-created and used for system health notifications
        (e.g., alert evaluation failures, service crashes, etc.)
        """
        with self.get_session() as session:
            # Check if system rule already exists
            rule = session.query(AlertRuleV2).filter(
                AlertRuleV2.kind == "system_error",
                AlertRuleV2.scope == "system"
            ).first()

            if rule:
                return rule

            # Create new system rule
            import uuid
            rule = AlertRuleV2(
                id=str(uuid.uuid4()),
                name="Alert System Health",
                description="Notifications for alert system failures and internal errors",
                scope="system",
                kind="system_error",
                enabled=True,
                severity="error",
                cooldown_seconds=3600,  # 1 hour cooldown to prevent spam
                auto_resolve=False,
                suppress_during_updates=False,
                notify_channels_json=None,  # Will use default channels
                created_by="system"
            )
            session.add(rule)
            session.commit()
            session.refresh(rule)
            logger.info("Created system alert rule for health monitoring")
            return rule

    def create_alert_rule_v2(
        self,
        name: str,
        description: Optional[str],
        scope: str,
        kind: str,
        enabled: bool,
        severity: str,
        metric: Optional[str] = None,
        threshold: Optional[float] = None,
        operator: Optional[str] = None,
        duration_seconds: Optional[int] = None,
        occurrences: Optional[int] = None,
        clear_threshold: Optional[float] = None,
        clear_duration_seconds: Optional[int] = None,
        cooldown_seconds: int = 300,
        auto_resolve: bool = False,
        suppress_during_updates: bool = False,
        host_selector_json: Optional[str] = None,
        container_selector_json: Optional[str] = None,
        labels_json: Optional[str] = None,
        notify_channels_json: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> AlertRuleV2:
        """Create a new alert rule v2"""
        import uuid

        with self.get_session() as session:
            rule = AlertRuleV2(
                id=str(uuid.uuid4()),
                name=name,
                description=description,
                scope=scope,
                kind=kind,
                enabled=enabled,
                severity=severity,
                metric=metric,
                threshold=threshold,
                operator=operator,
                duration_seconds=duration_seconds,
                occurrences=occurrences,
                clear_threshold=clear_threshold,
                clear_duration_seconds=clear_duration_seconds,
                cooldown_seconds=cooldown_seconds,
                auto_resolve=auto_resolve,
                suppress_during_updates=suppress_during_updates,
                host_selector_json=host_selector_json,
                container_selector_json=container_selector_json,
                labels_json=labels_json,
                notify_channels_json=notify_channels_json,
                created_by=created_by,
            )
            session.add(rule)
            session.commit()
            session.refresh(rule)
            logger.info(f"Created alert rule v2: {name} (ID: {rule.id})")
            return rule

    def update_alert_rule_v2(self, rule_id: str, **updates) -> Optional[AlertRuleV2]:
        """Update an alert rule v2"""
        with self.get_session() as session:
            rule = session.query(AlertRuleV2).filter(AlertRuleV2.id == rule_id).first()
            if not rule:
                logger.warning(f"Attempted to update non-existent alert rule v2 {rule_id}")
                return None

            # Update fields
            for key, value in updates.items():
                if hasattr(rule, key) and key not in ['id', 'created_at', 'created_by']:
                    setattr(rule, key, value)

            # Increment version
            rule.version += 1
            rule.updated_at = datetime.now(timezone.utc)

            session.commit()
            session.refresh(rule)
            logger.info(f"Updated alert rule v2: {rule.name} (ID: {rule_id}, version: {rule.version})")
            return rule

    def delete_alert_rule_v2(self, rule_id: str) -> bool:
        """Delete an alert rule v2"""
        with self.get_session() as session:
            try:
                rule = session.query(AlertRuleV2).filter(AlertRuleV2.id == rule_id).first()
                if rule:
                    rule_name = rule.name
                    session.delete(rule)
                    session.commit()
                    logger.info(f"Deleted alert rule v2: {rule_name} (ID: {rule_id})")
                    return True
                logger.warning(f"Attempted to delete non-existent alert rule v2 {rule_id}")
                return False
            except Exception as e:
                logger.error(f"Failed to delete alert rule v2 {rule_id}: {e}")
                raise

    # V1 method get_alerts_dependent_on_channel() removed - V1 alert system removed

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
                   category: Optional[List[str]] = None,
                   event_type: Optional[str] = None,
                   severity: Optional[List[str]] = None,
                   host_id: Optional[List[str]] = None,
                   container_id: Optional[List[str]] = None,
                   container_name: Optional[str] = None,
                   start_date: Optional[datetime] = None,
                   end_date: Optional[datetime] = None,
                   correlation_id: Optional[str] = None,
                   search: Optional[str] = None,
                   limit: int = 100,
                   offset: int = 0,
                   sort_order: str = 'desc') -> tuple[List[EventLog], int]:
        """Get events with filtering and pagination - returns (events, total_count)

        Multi-select filters (category, severity, host_id, container_id) accept lists for OR filtering.
        """
        with self.get_session() as session:
            query = session.query(EventLog)

            # Apply filters - use IN clause for lists
            if category:
                if isinstance(category, list) and category:
                    query = query.filter(EventLog.category.in_(category))
                elif isinstance(category, str):
                    query = query.filter(EventLog.category == category)
            if event_type:
                query = query.filter(EventLog.event_type == event_type)
            if severity:
                if isinstance(severity, list) and severity:
                    query = query.filter(EventLog.severity.in_(severity))
                elif isinstance(severity, str):
                    query = query.filter(EventLog.severity == severity)
            # Special handling for host_id + container_id combination
            # When filtering by container_id, include events even if host_id is NULL
            # (v2 alerts don't have host_id set)
            if host_id and container_id:
                from sqlalchemy import or_
                if isinstance(container_id, list) and container_id:
                    container_filter = EventLog.container_id.in_(container_id)
                elif isinstance(container_id, str):
                    container_filter = EventLog.container_id == container_id
                else:
                    container_filter = None

                if isinstance(host_id, list) and host_id:
                    host_filter = EventLog.host_id.in_(host_id)
                elif isinstance(host_id, str):
                    host_filter = EventLog.host_id == host_id
                else:
                    host_filter = None

                if container_filter is not None and host_filter is not None:
                    # Include events that match container_id AND (host_id matches OR host_id is NULL)
                    query = query.filter(container_filter & (host_filter | (EventLog.host_id == None)))
                elif container_filter is not None:
                    query = query.filter(container_filter)
                elif host_filter is not None:
                    query = query.filter(host_filter)
            elif host_id:
                if isinstance(host_id, list) and host_id:
                    query = query.filter(EventLog.host_id.in_(host_id))
                elif isinstance(host_id, str):
                    query = query.filter(EventLog.host_id == host_id)
            elif container_id:
                if isinstance(container_id, list) and container_id:
                    query = query.filter(EventLog.container_id.in_(container_id))
                elif isinstance(container_id, str):
                    query = query.filter(EventLog.container_id == container_id)
            if container_name:
                # Escape LIKE wildcards to prevent unintended pattern matching
                escaped_name = container_name.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
                query = query.filter(EventLog.container_name.like(f'%{escaped_name}%', escape='\\'))
            if start_date:
                query = query.filter(EventLog.timestamp >= start_date)
            if end_date:
                query = query.filter(EventLog.timestamp <= end_date)
            if correlation_id:
                query = query.filter(EventLog.correlation_id == correlation_id)
            if search:
                # Escape LIKE wildcards to prevent unintended pattern matching
                escaped_search = search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
                search_term = f'%{escaped_search}%'
                query = query.filter(
                    (EventLog.title.like(search_term, escape='\\')) |
                    (EventLog.message.like(search_term, escape='\\')) |
                    (EventLog.container_name.like(search_term, escape='\\'))
                )

            # Get total count for pagination
            total_count = query.count()

            # Apply ordering based on sort_order preference, limit and offset
            if sort_order == 'asc':
                events = query.order_by(EventLog.timestamp.asc()).offset(offset).limit(limit).all()
            else:
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
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
            deleted_count = session.query(EventLog).filter(
                EventLog.timestamp < cutoff_date
            ).delete()
            session.commit()
            return deleted_count

    def cleanup_old_alerts(self, retention_days: int) -> int:
        """
        Delete resolved alerts older than retention_days

        Args:
            retention_days: Number of days to keep resolved alerts (0 = keep forever)

        Returns:
            Number of alerts deleted
        """
        if retention_days <= 0:
            return 0

        with self.get_session() as session:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
            deleted_count = session.query(AlertV2).filter(
                AlertV2.state == 'resolved',
                AlertV2.resolved_at < cutoff_date
            ).delete()
            session.commit()
            logger.info(f"Cleaned up {deleted_count} resolved alerts older than {retention_days} days")
            return deleted_count

    def cleanup_old_rule_evaluations(self, hours: int = 24) -> int:
        """
        Delete rule evaluations older than hours

        Rule evaluations are used for debugging and don't need long retention.
        Default: 24 hours

        Args:
            hours: Number of hours to keep evaluations

        Returns:
            Number of evaluations deleted
        """
        with self.get_session() as session:
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
            deleted_count = session.query(RuleEvaluation).filter(
                RuleEvaluation.timestamp < cutoff_time
            ).delete()
            session.commit()
            logger.info(f"Cleaned up {deleted_count} rule evaluations older than {hours} hours")
            return deleted_count

    def cleanup_orphaned_rule_runtime(self, existing_container_keys: set) -> int:
        """
        Delete RuleRuntime entries for containers that no longer exist

        RuleRuntime stores sliding window state for metric alerts. When containers
        are deleted, these entries become orphaned and waste database space.

        Args:
            existing_container_keys: Set of composite keys (host_id:container_id) for existing containers

        Returns:
            Number of runtime entries deleted
        """
        with self.get_session() as session:
            # Get all runtime entries
            all_runtime = session.query(RuleRuntime).all()

            deleted_count = 0
            for runtime in all_runtime:
                # RuleRuntime.dedup_key format: {rule_id}|{scope_type}:{scope_id}
                # We need to extract the scope part to check if container exists
                try:
                    # Parse dedup_key: "rule-123|container:host-id:container-id"
                    if '|' in runtime.dedup_key:
                        _, scope_part = runtime.dedup_key.split('|', 1)
                        if ':' in scope_part:
                            scope_type, scope_id = scope_part.split(':', 1)

                            # Only clean up container-scoped runtime entries
                            if scope_type == 'container':
                                # scope_id might be SHORT ID or composite key depending on context
                                # Check both formats for safety
                                if scope_id not in existing_container_keys:
                                    # Also check if it's a SHORT ID that exists in any composite key
                                    short_id_exists = any(scope_id in key for key in existing_container_keys)
                                    if not short_id_exists:
                                        session.delete(runtime)
                                        deleted_count += 1
                except Exception as e:
                    logger.warning(f"Error parsing RuleRuntime dedup_key '{runtime.dedup_key}': {e}")
                    continue

            if deleted_count > 0:
                session.commit()
                logger.info(f"Cleaned up {deleted_count} orphaned RuleRuntime entries")

            return deleted_count

    def get_event_statistics(self,
                           start_date: Optional[datetime] = None,
                           end_date: Optional[datetime] = None) -> Dict[str, Any]:
        """Get event statistics for dashboard

        BUG FIX: Apply date filters to ALL queries to ensure consistent counts.
        Previously, category_counts and severity_counts ignored the date filters,
        causing total_events to differ from the sum of categories/severities.
        """
        with self.get_session() as session:
            # Build base query with date filters
            query = session.query(EventLog)

            if start_date:
                query = query.filter(EventLog.timestamp >= start_date)
            if end_date:
                query = query.filter(EventLog.timestamp <= end_date)

            total_events = query.count()

            # BUG FIX: Reuse filtered query for category counts
            # Previous code created a new query that ignored date filters
            category_counts = {}
            for category, count in query.with_entities(
                EventLog.category,
                session.func.count(EventLog.id)
            ).group_by(EventLog.category).all():
                category_counts[category] = count

            # BUG FIX: Reuse filtered query for severity counts
            # Previous code created a new query that ignored date filters
            severity_counts = {}
            for severity, count in query.with_entities(
                EventLog.severity,
                session.func.count(EventLog.id)
            ).group_by(EventLog.severity).all():
                severity_counts[severity] = count

            return {
                'total_events': total_events,
                'category_counts': category_counts,
                'severity_counts': severity_counts,
                'period_start': start_date.isoformat() + 'Z' if start_date else None,
                'period_end': end_date.isoformat() + 'Z' if end_date else None
            }


    # User management methods
    def _hash_password(self, password: str) -> str:
        """Hash a password using bcrypt with salt"""
        # Generate salt and hash password
        salt = bcrypt.gensalt(rounds=12)  # 12 rounds is a good balance of security/speed
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')

    def _verify_password(self, password: str, hashed: str) -> bool:
        """
        Verify a password against a bcrypt or Argon2id hash.

        BACKWARD COMPATIBILITY: Supports both bcrypt (v1) and Argon2id (v2) hashes.
        """
        # Try Argon2id first (v2 format: starts with $argon2id$)
        if hashed.startswith('$argon2id$'):
            try:
                from argon2 import PasswordHasher
                from argon2.exceptions import VerifyMismatchError
                ph = PasswordHasher()
                ph.verify(hashed, password)
                return True
            except VerifyMismatchError:
                return False
            except Exception as e:
                logger.error(f"Argon2id verification failed: {e}")
                return False

        # Fall back to bcrypt (v1 format)
        try:
            return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
        except Exception as e:
            logger.error(f"bcrypt verification failed: {e}")
            return False

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

            # Prevent timing attack: always run bcrypt even if user doesn't exist
            if user:
                is_valid = self._verify_password(password, user.password_hash)
            else:
                # Run dummy bcrypt to maintain constant time
                dummy_hash = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYFj.N/wx9S"
                self._verify_password(password, dummy_hash)
                is_valid = False

            if user and is_valid:
                # Update last login
                user.last_login = datetime.now(timezone.utc)
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
                user.updated_at = datetime.now(timezone.utc)
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
                user.updated_at = datetime.now(timezone.utc)
                session.commit()
                logger.info(f"Username changed from {old_username} to {new_username}")
                return True
            return False

    def update_display_name(self, username: str, display_name: str) -> bool:
        """Update user's display name"""
        with self.get_session() as session:
            user = session.query(User).filter(User.username == username).first()
            if user:
                user.display_name = display_name if display_name.strip() else None
                user.updated_at = datetime.now(timezone.utc)
                session.commit()
                logger.info(f"Display name updated for user {username}: {display_name}")
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
            user.updated_at = datetime.now(timezone.utc)
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
                user.updated_at = datetime.now(timezone.utc)
                session.commit()
                return True
            return False

    def get_modal_preferences(self, username: str) -> Optional[str]:
        """Get modal preferences for a user"""
        with self.get_session() as session:
            user = session.query(User).filter(User.username == username).first()
            if user:
                return user.modal_preferences
            return None

    def save_modal_preferences(self, username: str, preferences: str) -> bool:
        """Save modal preferences for a user"""
        with self.get_session() as session:
            user = session.query(User).filter(User.username == username).first()
            if user:
                user.modal_preferences = preferences
                user.updated_at = datetime.now(timezone.utc)
                session.commit()
                return True
            return False

    def get_event_sort_order(self, username: str) -> str:
        """Get event sort order preference for a user"""
        with self.get_session() as session:
            user = session.query(User).filter(User.username == username).first()
            if user and user.event_sort_order:
                return user.event_sort_order
            return 'desc'  # Default to newest first

    def save_event_sort_order(self, username: str, sort_order: str) -> bool:
        """Save event sort order preference for a user"""
        with self.get_session() as session:
            user = session.query(User).filter(User.username == username).first()
            if user:
                # Validate sort order
                if sort_order not in ['asc', 'desc']:
                    return False
                user.event_sort_order = sort_order
                user.updated_at = datetime.now(timezone.utc)
                session.commit()
                return True
            return False

    def get_container_sort_order(self, username: str) -> str:
        """Get container sort order preference for a user"""
        with self.get_session() as session:
            user = session.query(User).filter(User.username == username).first()
            if user and user.container_sort_order:
                return user.container_sort_order
            return 'name-asc'  # Default to name A-Z

    def save_container_sort_order(self, username: str, sort_order: str) -> bool:
        """Save container sort order preference for a user"""
        with self.get_session() as session:
            user = session.query(User).filter(User.username == username).first()
            if user:
                # Validate sort order
                valid_sorts = ['name-asc', 'name-desc', 'status', 'memory-desc', 'memory-asc', 'cpu-desc', 'cpu-asc']
                if sort_order not in valid_sorts:
                    return False
                user.container_sort_order = sort_order
                user.updated_at = datetime.now(timezone.utc)
                session.commit()
                return True
            return False