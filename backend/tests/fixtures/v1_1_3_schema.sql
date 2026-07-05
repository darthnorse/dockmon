-- DockMon v1.1.3 schema fixture (schema only, no data).
--
-- This is the oldest database the Alembic chain supports: migration
-- 001_v2_0_0 ALTERs these tables rather than creating them, so the
-- chain can only run against this baseline. Used by test_schema_parity.py
-- to prove fresh installs (Base.metadata.create_all) and upgraded
-- databases (this fixture + alembic upgrade head) end up with an
-- identical schema.
--
-- Regenerate: git show v1.1.3:backend/database.py, run
-- Base.metadata.create_all() against an empty SQLite file, then dump
-- sqlite_master.sql (excluding sqlite_* internals). The v1.1.3 ad-hoc
-- DatabaseManager._run_migrations() columns are already present in the
-- v1.1.3 models, so create_all output is the fully-migrated v1.1.3 schema.

CREATE TABLE alert_rule_containers (
	id INTEGER NOT NULL, 
	alert_rule_id VARCHAR NOT NULL, 
	host_id VARCHAR NOT NULL, 
	container_name VARCHAR NOT NULL, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT _alert_container_uc UNIQUE (alert_rule_id, host_id, container_name), 
	FOREIGN KEY(alert_rule_id) REFERENCES alert_rules (id) ON DELETE CASCADE, 
	FOREIGN KEY(host_id) REFERENCES docker_hosts (id) ON DELETE CASCADE
);

CREATE TABLE alert_rules (
	id VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	trigger_events JSON, 
	trigger_states JSON, 
	notification_channels JSON NOT NULL, 
	cooldown_minutes INTEGER, 
	enabled BOOLEAN, 
	last_triggered DATETIME, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id)
);

CREATE TABLE auto_restart_configs (
	id INTEGER NOT NULL, 
	host_id VARCHAR, 
	container_id VARCHAR NOT NULL, 
	container_name VARCHAR NOT NULL, 
	enabled BOOLEAN, 
	max_retries INTEGER, 
	retry_delay INTEGER, 
	restart_count INTEGER, 
	last_restart DATETIME, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(host_id) REFERENCES docker_hosts (id)
);

CREATE TABLE docker_hosts (
	id VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	url VARCHAR NOT NULL, 
	tls_cert TEXT, 
	tls_key TEXT, 
	tls_ca TEXT, 
	security_status VARCHAR, 
	is_active BOOLEAN, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

CREATE TABLE event_logs (
	id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, 
	correlation_id VARCHAR, 
	category VARCHAR NOT NULL, 
	event_type VARCHAR NOT NULL, 
	severity VARCHAR NOT NULL, 
	host_id VARCHAR, 
	host_name VARCHAR, 
	container_id VARCHAR, 
	container_name VARCHAR, 
	title VARCHAR NOT NULL, 
	message TEXT, 
	old_state VARCHAR, 
	new_state VARCHAR, 
	triggered_by VARCHAR, 
	details JSON, 
	duration_ms INTEGER, 
	timestamp DATETIME NOT NULL
);

CREATE TABLE global_settings (
	id INTEGER NOT NULL, 
	max_retries INTEGER, 
	retry_delay INTEGER, 
	default_auto_restart BOOLEAN, 
	polling_interval INTEGER, 
	connection_timeout INTEGER, 
	log_retention_days INTEGER, 
	event_retention_days INTEGER, 
	enable_notifications BOOLEAN, 
	auto_cleanup_events BOOLEAN, 
	alert_template TEXT, 
	blackout_windows JSON, 
	first_run_complete BOOLEAN, 
	polling_interval_migrated BOOLEAN, 
	timezone_offset INTEGER, 
	show_host_stats BOOLEAN, 
	show_container_stats BOOLEAN, 
	updated_at DATETIME, 
	PRIMARY KEY (id)
);

CREATE TABLE notification_channels (
	id INTEGER NOT NULL, 
	name VARCHAR NOT NULL, 
	type VARCHAR NOT NULL, 
	config JSON NOT NULL, 
	enabled BOOLEAN, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

CREATE TABLE users (
	id INTEGER NOT NULL, 
	username VARCHAR NOT NULL, 
	password_hash VARCHAR NOT NULL, 
	is_first_login BOOLEAN, 
	must_change_password BOOLEAN, 
	dashboard_layout TEXT, 
	event_sort_order VARCHAR, 
	container_sort_order VARCHAR, 
	modal_preferences TEXT, 
	created_at DATETIME, 
	updated_at DATETIME, 
	last_login DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (username)
);

