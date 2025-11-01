"""
Agent manager for registration, authentication, and lifecycle management.

Handles:
- Registration token generation and validation (15-minute expiry)
- Agent registration with token-based authentication
- Agent reconnection with agent_id validation
- Host creation for agent-based connections
"""
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from database import RegistrationToken, Agent, DockerHostDB, DatabaseManager

logger = logging.getLogger(__name__)


class AgentManager:
    """Manages agent registration and lifecycle"""

    def __init__(self):
        """
        Initialize AgentManager.

        Creates short-lived database sessions for each operation instead of
        using a persistent session (following the pattern used throughout DockMon).
        """
        self.db_manager = DatabaseManager()  # Creates sessions as needed

    def generate_registration_token(self, user_id: int) -> RegistrationToken:
        """
        Generate a single-use registration token with 15-minute expiry.

        Args:
            user_id: ID of user creating the token

        Returns:
            RegistrationToken: Created token record
        """
        now = datetime.now(timezone.utc)
        token = str(uuid.uuid4())  # 36 characters with hyphens (e.g., 550e8400-e29b-41d4-a716-446655440000)

        logger.info(f"Generating registration token for user {user_id}: {token[:8]}...")

        with self.db_manager.get_session() as session:
            token_record = RegistrationToken(
                token=token,
                created_by_user_id=user_id,
                created_at=now,
                expires_at=now + timedelta(minutes=15),
                used=False,
                used_at=None
            )

            session.add(token_record)
            session.commit()
            session.refresh(token_record)

            logger.info(f"Successfully created registration token {token[:8]}... (expires: {token_record.expires_at})")

            return token_record

    def validate_registration_token(self, token: str) -> bool:
        """
        Validate registration token is valid, unused, and not expired.

        Args:
            token: Token string to validate

        Returns:
            bool: True if valid, False otherwise
        """
        logger.info(f"Validating registration token {token[:8]}...")

        with self.db_manager.get_session() as session:
            token_record = session.query(RegistrationToken).filter_by(token=token).first()

            if not token_record:
                logger.warning(f"Token {token[:8]}... not found in database")
                return False

            if token_record.used:
                logger.warning(f"Token {token[:8]}... already used")
                return False

            now = datetime.now(timezone.utc)
            # SQLite stores datetimes as naive, so we need to make expires_at timezone-aware for comparison
            expires_at = token_record.expires_at.replace(tzinfo=timezone.utc) if token_record.expires_at.tzinfo is None else token_record.expires_at
            if expires_at <= now:
                logger.warning(f"Token {token[:8]}... expired at {token_record.expires_at}")
                return False

            logger.info(f"Token {token[:8]}... is valid")
            return True

    def validate_permanent_token(self, token: str) -> bool:
        """
        Validate permanent token (agent_id) exists.

        Args:
            token: Permanent token (agent_id)

        Returns:
            bool: True if valid agent_id exists, False otherwise
        """
        with self.db_manager.get_session() as session:
            agent = session.query(Agent).filter_by(id=token).first()
            return agent is not None

    def register_agent(self, registration_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Register a new agent with token-based authentication.

        Creates:
        - Agent record with provided metadata
        - DockerHost record with connection_type='agent'
        - Marks registration token as used

        Args:
            registration_data: Dict containing:
                - token: Registration token
                - engine_id: Docker engine ID
                - version: Agent version
                - proto_version: Protocol version
                - capabilities: Dict of agent capabilities

        Returns:
            Dict with:
                - success: bool
                - agent_id: str (on success)
                - host_id: str (on success)
                - error: str (on failure)
        """
        token = registration_data.get("token")
        engine_id = registration_data.get("engine_id")
        hostname = registration_data.get("hostname")
        version = registration_data.get("version")
        proto_version = registration_data.get("proto_version")
        capabilities = registration_data.get("capabilities", {})

        # Log what we received for debugging
        logger.info(f"Registration data keys: {list(registration_data.keys())}")
        logger.info(f"Full registration data: {registration_data}")
        logger.info(f"Hostname: {hostname}, Engine ID: {engine_id[:12]}...")

        # Check if token is a permanent token (agent_id for reconnection)
        is_permanent_token = self.validate_permanent_token(token)

        # Validate token (either registration token or permanent token)
        if not is_permanent_token and not self.validate_registration_token(token):
            with self.db_manager.get_session() as session:
                token_record = session.query(RegistrationToken).filter_by(token=token).first()
                if token_record:
                    # SQLite stores datetimes as naive, make it timezone-aware for comparison
                    expires_at = token_record.expires_at.replace(tzinfo=timezone.utc) if token_record.expires_at.tzinfo is None else token_record.expires_at
                    if expires_at <= datetime.now(timezone.utc):
                        return {"success": False, "error": "Registration token has expired"}
                elif token_record and token_record.used:
                    return {"success": False, "error": "Registration token has already been used"}
                else:
                    return {"success": False, "error": "Invalid registration token"}

        # If using permanent token, find existing agent
        if is_permanent_token:
            with self.db_manager.get_session() as session:
                existing_agent = session.query(Agent).filter_by(id=token).first()
                if existing_agent and existing_agent.engine_id == engine_id:
                    # Update existing agent with new version/capabilities
                    existing_agent.version = version
                    existing_agent.proto_version = proto_version
                    existing_agent.capabilities = json.dumps(capabilities)
                    existing_agent.status = "online"
                    existing_agent.last_seen_at = datetime.now(timezone.utc)

                    # Update host record with fresh system information
                    host = session.query(DockerHostDB).filter_by(id=existing_agent.host_id).first()
                    if host:
                        host.updated_at = datetime.now(timezone.utc)
                        # Update hostname if provided (agent may have been updated)
                        if hostname:
                            host.name = hostname
                        # Update system information (keep data fresh on reconnection)
                        if registration_data.get("os_type"):
                            host.os_type = registration_data.get("os_type")
                        if registration_data.get("os_version"):
                            host.os_version = registration_data.get("os_version")
                        if registration_data.get("kernel_version"):
                            host.kernel_version = registration_data.get("kernel_version")
                        if registration_data.get("docker_version"):
                            host.docker_version = registration_data.get("docker_version")
                        if registration_data.get("daemon_started_at"):
                            host.daemon_started_at = registration_data.get("daemon_started_at")
                        if registration_data.get("total_memory"):
                            host.total_memory = registration_data.get("total_memory")
                        if registration_data.get("num_cpus"):
                            host.num_cpus = registration_data.get("num_cpus")

                    session.commit()

                    return {
                        "success": True,
                        "agent_id": existing_agent.id,
                        "host_id": existing_agent.host_id,
                        "permanent_token": existing_agent.id
                    }
                else:
                    return {"success": False, "error": "Permanent token does not match engine_id"}

        # Check if engine_id already registered as agent
        with self.db_manager.get_session() as session:
            existing_agent = session.query(Agent).filter_by(engine_id=engine_id).first()
            if existing_agent:
                return {"success": False, "error": "Agent with this engine_id is already registered"}

            # Check for migration: engine_id matches existing host
            existing_host = session.query(DockerHostDB).filter_by(engine_id=engine_id).first()
            if existing_host:
                # Migration detected - but we need to validate connection type
                logger.info(f"Duplicate engine_id detected: {engine_id[:12]}... matches existing host {existing_host.name} ({existing_host.id[:8]}...), connection_type={existing_host.connection_type}")

                # REJECT migration for local connections
                # Local Docker socket is the ONLY way to manage localhost
                # Agents are ONLY for remote hosts
                if existing_host.connection_type == 'local':
                    logger.warning(f"Migration rejected: Cannot migrate local Docker socket connection to agent. "
                                  f"Host '{existing_host.name}' uses local socket - agents are only for remote hosts.")
                    return {
                        "success": False,
                        "error": "Migration not supported for local Docker connections. "
                                "Agents are only for remote hosts. "
                                "Local Docker monitoring via socket is the preferred method for localhost."
                    }

                # ALLOW migration for remote connections only
                if existing_host.connection_type == 'remote':
                    # Reject if host already migrated (has replaced_by_host_id set)
                    if existing_host.replaced_by_host_id is not None:
                        logger.warning(f"Migration rejected: Host {existing_host.name} has already been migrated")
                        return {"success": False, "error": f"Host with this engine_id has already been migrated"}

                    # Perform migration
                    logger.info(f"Migration allowed: remote host {existing_host.name} → agent")
                    migration_result = self._migrate_host_to_agent(
                        existing_host=existing_host,
                        engine_id=engine_id,
                        hostname=hostname,
                        version=version,
                        proto_version=proto_version,
                        capabilities=capabilities,
                        registration_data=registration_data,
                        token=token
                    )

                    return migration_result

                # For any other connection type (including 'agent'), reject
                logger.error(f"Unexpected connection type '{existing_host.connection_type}' for engine_id {engine_id[:12]}...")
                return {
                    "success": False,
                    "error": f"Host with this engine_id already exists with connection type '{existing_host.connection_type}'"
                }

        # Generate IDs
        agent_id = str(uuid.uuid4())
        host_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)  # Naive UTC datetime

        logger.info(f"Registering new agent {agent_id[:8]}... with engine_id {engine_id[:12]}...")
        logger.info(f"System info - OS: {registration_data.get('os_type')} {registration_data.get('os_version')}, "
                    f"Docker: {registration_data.get('docker_version')}, "
                    f"Memory: {registration_data.get('total_memory')}, CPUs: {registration_data.get('num_cpus')}")

        # Use a NEW dedicated session for registration to ensure immediate commit
        # The WebSocket session stays open for the connection lifetime, preventing visibility
        with self.db_manager.get_session() as reg_session:
            try:
                # Create host record with hostname (fallback to engine_id if not provided)
                agent_name = hostname if hostname else f"Agent-{engine_id[:12]}"
                host = DockerHostDB(
                    id=host_id,
                    name=agent_name,
                    url="agent://",  # Placeholder URL for agent connections (not used for WebSocket)
                    connection_type="agent",
                    engine_id=engine_id,  # Required for migration detection
                    created_at=now,
                    updated_at=now,
                    # System information (aligned with legacy host schema)
                    os_type=registration_data.get("os_type"),
                    os_version=registration_data.get("os_version"),
                    kernel_version=registration_data.get("kernel_version"),
                    docker_version=registration_data.get("docker_version"),
                    daemon_started_at=registration_data.get("daemon_started_at"),
                    total_memory=registration_data.get("total_memory"),
                    num_cpus=registration_data.get("num_cpus")
                )
                reg_session.add(host)
                reg_session.flush()  # Ensure host exists before creating agent
                logger.info(f"Created host record: {agent_name} ({host_id[:8]}...)")

                # Create agent record
                agent = Agent(
                    id=agent_id,
                    host_id=host_id,
                    engine_id=engine_id,
                    version=version,
                    proto_version=proto_version,
                    capabilities=json.dumps(capabilities),  # Store as JSON string
                    status="online",
                    last_seen_at=now,
                    registered_at=now
                )
                reg_session.add(agent)
                logger.info(f"Created agent record: {agent_id[:8]}...")

                # Mark token as used
                token_record = reg_session.query(RegistrationToken).filter_by(token=token).first()
                if token_record:
                    token_record.used = True
                    token_record.used_at = now

                # Commit in the dedicated session (context manager will close it)
                reg_session.commit()
                logger.info(f"Successfully registered agent {agent_id[:8]}... (host: {agent_name}, host_id: {host_id[:8]}...)")

                return {
                    "success": True,
                    "agent_id": agent_id,
                    "host_id": host_id,
                    "permanent_token": agent_id  # Use agent_id as permanent token for reconnection
                }

            except IntegrityError as e:
                reg_session.rollback()
                return {"success": False, "error": f"Database integrity error: {str(e)}"}
            except Exception as e:
                reg_session.rollback()
                return {"success": False, "error": f"Registration failed: {str(e)}"}

    def reconnect_agent(self, reconnect_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Reconnect an existing agent.

        Validates agent_id exists and engine_id matches stored value.

        Args:
            reconnect_data: Dict containing:
                - agent_id: Agent ID
                - engine_id: Docker engine ID (must match stored value)

        Returns:
            Dict with:
                - success: bool
                - agent_id: str (on success)
                - error: str (on failure)
        """
        agent_id = reconnect_data.get("agent_id")
        engine_id = reconnect_data.get("engine_id")

        with self.db_manager.get_session() as session:
            # Find agent
            agent = session.query(Agent).filter_by(id=agent_id).first()

            if not agent:
                return {"success": False, "error": "Agent not found"}

            # Validate engine_id matches
            if agent.engine_id != engine_id:
                return {"success": False, "error": "Engine_id mismatch: agent verification failed"}

            # Update last_seen_at
            agent.last_seen_at = datetime.now(timezone.utc)  # Naive UTC datetime
            agent.status = "online"
            session.commit()

            return {
                "success": True,
                "agent_id": agent_id
            }

    def get_agent_for_host(self, host_id: str) -> str:
        """
        Get the agent ID for a given host ID.

        Args:
            host_id: Docker host ID

        Returns:
            Agent ID (str) if agent exists for this host, None otherwise
        """
        with self.db_manager.get_session() as session:
            agent = session.query(Agent).filter_by(host_id=host_id).first()
            return agent.id if agent else None

    def _migrate_host_to_agent(
        self,
        existing_host: DockerHostDB,
        engine_id: str,
        hostname: str,
        version: str,
        proto_version: str,
        capabilities: dict,
        registration_data: dict,
        token: str
    ) -> dict:
        """
        Migrate an existing mTLS/remote host to agent-based connection.

        This performs:
        1. Create new agent-based host
        2. Transfer container settings (auto-restart, tags, desired states)
        3. Mark old host as inactive (is_active=False, replaced_by_host_id set)
        4. Return migration info (WebSocket handler broadcasts notification)

        Args:
            existing_host: Existing DockerHostDB record to migrate from
            engine_id: Docker engine ID
            hostname: Agent hostname
            version: Agent version
            proto_version: Protocol version
            capabilities: Agent capabilities
            registration_data: Full registration data
            token: Registration token

        Returns:
            Dict with success, agent_id, host_id, migration_detected, migrated_from
        """
        from database import AutoRestartConfig, TagAssignment, ContainerDesiredState

        old_host_id = existing_host.id
        old_host_name = existing_host.name

        # Generate new IDs
        agent_id = str(uuid.uuid4())
        new_host_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        logger.info(f"Starting migration: {old_host_name} ({old_host_id[:8]}...) → agent {hostname} ({new_host_id[:8]}...)")

        # Use dedicated session for migration (atomic transaction)
        with self.db_manager.get_session() as session:
            try:
                # Step 1: Create new agent host
                agent_name = hostname if hostname else f"Agent-{engine_id[:12]}"
                new_host = DockerHostDB(
                    id=new_host_id,
                    name=agent_name,
                    url="agent://",
                    connection_type="agent",
                    engine_id=engine_id,
                    created_at=now,
                    updated_at=now,
                    # Copy system information from existing host
                    os_type=registration_data.get("os_type") or existing_host.os_type,
                    os_version=registration_data.get("os_version") or existing_host.os_version,
                    kernel_version=registration_data.get("kernel_version") or existing_host.kernel_version,
                    docker_version=registration_data.get("docker_version") or existing_host.docker_version,
                    daemon_started_at=registration_data.get("daemon_started_at") or existing_host.daemon_started_at,
                    total_memory=registration_data.get("total_memory") or existing_host.total_memory,
                    num_cpus=registration_data.get("num_cpus") or existing_host.num_cpus
                )
                session.add(new_host)
                session.flush()
                logger.info(f"Created new agent host: {agent_name} ({new_host_id[:8]}...)")

                # Step 2: Create agent record
                agent = Agent(
                    id=agent_id,
                    host_id=new_host_id,
                    engine_id=engine_id,
                    version=version,
                    proto_version=proto_version,
                    capabilities=json.dumps(capabilities),
                    status="online",
                    last_seen_at=now,
                    registered_at=now
                )
                session.add(agent)
                logger.info(f"Created agent record: {agent_id[:8]}...")

                # Step 3: Transfer container settings
                # Get all containers for old host (extract short container ID from composite key)
                # Composite key format: {host_id}:{container_id_12char}
                transferred_count = 0

                # Transfer auto-restart configs
                auto_restarts = session.query(AutoRestartConfig).filter_by(host_id=old_host_id).all()
                for ar in auto_restarts:
                    # Extract short container ID from composite key
                    old_composite = ar.container_id
                    if ':' in old_composite:
                        _, short_container_id = old_composite.split(':', 1)
                        new_composite = f"{new_host_id}:{short_container_id}"

                        # Create new record with updated composite key
                        new_ar = AutoRestartConfig(
                            container_id=new_composite,
                            host_id=new_host_id,
                            enabled=ar.enabled
                        )
                        session.add(new_ar)
                        transferred_count += 1

                        # Delete old record
                        session.delete(ar)

                # Transfer container tags
                tag_assignments = session.query(TagAssignment).filter(
                    TagAssignment.subject_type == 'container',
                    TagAssignment.subject_id.like(f"{old_host_id}:%")
                ).all()
                for tag_assignment in tag_assignments:
                    # Extract short container ID from composite key
                    old_composite = tag_assignment.subject_id
                    if ':' in old_composite:
                        _, short_container_id = old_composite.split(':', 1)
                        new_composite = f"{new_host_id}:{short_container_id}"

                        # Create new assignment with updated composite key
                        new_assignment = TagAssignment(
                            tag_id=tag_assignment.tag_id,
                            subject_type='container',
                            subject_id=new_composite,
                            compose_project=tag_assignment.compose_project,
                            compose_service=tag_assignment.compose_service,
                            host_id_at_attach=new_host_id,
                            container_name_at_attach=tag_assignment.container_name_at_attach
                        )
                        session.add(new_assignment)
                        transferred_count += 1

                        # Delete old assignment
                        session.delete(tag_assignment)

                # Transfer desired states
                desired_states = session.query(ContainerDesiredState).filter_by(host_id=old_host_id).all()
                for ds in desired_states:
                    # Extract short container ID from composite key
                    old_composite = ds.container_id
                    if ':' in old_composite:
                        _, short_container_id = old_composite.split(':', 1)
                        new_composite = f"{new_host_id}:{short_container_id}"

                        # Create new record with updated composite key
                        new_ds = ContainerDesiredState(
                            container_id=new_composite,
                            host_id=new_host_id,
                            container_name=ds.container_name,
                            desired_state=ds.desired_state,
                            custom_tags=ds.custom_tags,
                            web_ui_url=ds.web_ui_url
                        )
                        session.add(new_ds)

                        # Delete old record
                        session.delete(ds)
                        transferred_count += 1

                # Transfer container updates
                from database import ContainerUpdate
                container_updates = session.query(ContainerUpdate).filter_by(host_id=old_host_id).all()
                for cu in container_updates:
                    # Extract short container ID from composite key
                    old_composite = cu.container_id
                    if ':' in old_composite:
                        _, short_container_id = old_composite.split(':', 1)
                        new_composite = f"{new_host_id}:{short_container_id}"

                        # Create new record with updated composite key
                        new_cu = ContainerUpdate(
                            container_id=new_composite,
                            host_id=new_host_id,
                            current_image=cu.current_image,
                            current_digest=cu.current_digest,
                            latest_image=cu.latest_image,
                            latest_digest=cu.latest_digest,
                            update_available=cu.update_available,
                            floating_tag_mode=cu.floating_tag_mode,
                            auto_update_enabled=cu.auto_update_enabled,
                            update_policy=cu.update_policy,
                            health_check_strategy=cu.health_check_strategy,
                            health_check_url=cu.health_check_url,
                            last_checked_at=cu.last_checked_at,
                            last_updated_at=cu.last_updated_at,
                            registry_url=cu.registry_url,
                            platform=cu.platform,
                            changelog_url=cu.changelog_url,
                            changelog_source=cu.changelog_source,
                            changelog_checked_at=cu.changelog_checked_at,
                            registry_page_url=cu.registry_page_url,
                            registry_page_source=cu.registry_page_source
                        )
                        session.add(new_cu)
                        transferred_count += 1

                        # Delete old record
                        session.delete(cu)

                # Transfer container HTTP health checks
                from database import ContainerHttpHealthCheck
                health_checks = session.query(ContainerHttpHealthCheck).filter_by(host_id=old_host_id).all()
                for hc in health_checks:
                    # Extract short container ID from composite key
                    old_composite = hc.container_id
                    if ':' in old_composite:
                        _, short_container_id = old_composite.split(':', 1)
                        new_composite = f"{new_host_id}:{short_container_id}"

                        # Create new record with updated composite key (copy ALL fields)
                        new_hc = ContainerHttpHealthCheck(
                            container_id=new_composite,
                            host_id=new_host_id,
                            enabled=hc.enabled,
                            url=hc.url,
                            method=hc.method,
                            expected_status_codes=hc.expected_status_codes,
                            timeout_seconds=hc.timeout_seconds,
                            check_interval_seconds=hc.check_interval_seconds,
                            follow_redirects=hc.follow_redirects,
                            verify_ssl=hc.verify_ssl,
                            headers_json=hc.headers_json,
                            auth_config_json=hc.auth_config_json,
                            current_status=hc.current_status,
                            last_checked_at=hc.last_checked_at,
                            last_success_at=hc.last_success_at,
                            last_failure_at=hc.last_failure_at,
                            consecutive_successes=hc.consecutive_successes,
                            consecutive_failures=hc.consecutive_failures,
                            last_response_time_ms=hc.last_response_time_ms,
                            last_error_message=hc.last_error_message,
                            auto_restart_on_failure=hc.auto_restart_on_failure,
                            failure_threshold=hc.failure_threshold,
                            success_threshold=hc.success_threshold,
                            max_restart_attempts=hc.max_restart_attempts,
                            restart_retry_delay_seconds=hc.restart_retry_delay_seconds
                        )
                        session.add(new_hc)
                        transferred_count += 1

                        # Delete old record
                        session.delete(hc)

                # Transfer container alerts (scope_type='container')
                from database import AlertV2
                alerts = session.query(AlertV2).filter(
                    AlertV2.scope_type == 'container',
                    AlertV2.scope_id.like(f"{old_host_id}:%")
                ).all()
                for alert in alerts:
                    # Extract short container ID from composite scope_id
                    old_composite = alert.scope_id
                    if ':' in old_composite:
                        _, short_container_id = old_composite.split(':', 1)
                        new_composite = f"{new_host_id}:{short_container_id}"

                        # Update scope_id and dedup_key in place
                        old_dedup_key = alert.dedup_key
                        new_dedup_key = old_dedup_key.replace(old_composite, new_composite)

                        alert.scope_id = new_composite
                        alert.dedup_key = new_dedup_key
                        transferred_count += 1

                logger.info(f"Transferred {transferred_count} container settings from {old_host_name} to {agent_name}")

                # Step 4: Mark old host as migrated (set replaced_by_host_id and is_active=False)
                existing_host.replaced_by_host_id = new_host_id
                existing_host.is_active = False
                existing_host.updated_at = now
                logger.info(f"Marked old host {old_host_name} as migrated")

                # Step 5: Mark token as used
                token_record = session.query(RegistrationToken).filter_by(token=token).first()
                if token_record:
                    token_record.used = True
                    token_record.used_at = now

                # Commit all changes atomically
                session.commit()
                session.refresh(new_host)
                session.refresh(agent)

                logger.info(f"Migration completed successfully: {old_host_name} → {agent_name}")

                # Return success with migration info
                return {
                    "success": True,
                    "agent_id": agent_id,
                    "host_id": new_host_id,
                    "permanent_token": agent_id,
                    "migration_detected": True,
                    "migrated_from": {
                        "host_id": old_host_id,
                        "host_name": old_host_name
                    }
                }

            except Exception as e:
                session.rollback()
                logger.error(f"Migration failed: {e}", exc_info=True)
                return {"success": False, "error": f"Migration failed: {str(e)}"}
