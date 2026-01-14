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

    def __init__(self, monitor=None):
        """
        Initialize AgentManager.

        Creates short-lived database sessions for each operation instead of
        using a persistent session (following the pattern used throughout DockMon).

        Args:
            monitor: Optional DockerMonitor instance for notifying when hosts are created
        """
        self.db_manager = DatabaseManager()  # Creates sessions as needed
        self.monitor = monitor  # For adding hosts to monitor on registration

    def generate_registration_token(self, user_id: int, multi_use: bool = False) -> RegistrationToken:
        """
        Generate a registration token with 15-minute expiry.

        Args:
            user_id: ID of user creating the token
            multi_use: If True, token can be used by unlimited agents (within expiry window)

        Returns:
            RegistrationToken: Created token record
        """
        now = datetime.now(timezone.utc)
        token = str(uuid.uuid4())  # 36 characters with hyphens (e.g., 550e8400-e29b-41d4-a716-446655440000)

        # max_uses: 1 = single use (default), None = unlimited
        max_uses = None if multi_use else 1

        logger.info(f"Generating registration token for user {user_id}: {token[:8]}... (multi_use={multi_use})")

        with self.db_manager.get_session() as session:
            token_record = RegistrationToken(
                token=token,
                created_by_user_id=user_id,
                created_at=now,
                expires_at=now + timedelta(minutes=15),
                max_uses=max_uses,
                use_count=0,
                last_used_at=None
            )

            session.add(token_record)
            session.commit()
            session.refresh(token_record)

            logger.info(f"Successfully created registration token {token[:8]}... (expires: {token_record.expires_at}, max_uses={max_uses})")

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

            if token_record.is_exhausted:
                logger.warning(f"Token {token[:8]}... has reached max uses ({token_record.use_count}/{token_record.max_uses})")
                return False

            now = datetime.now(timezone.utc)
            # SQLite stores datetimes as naive, so we need to make expires_at timezone-aware for comparison
            expires_at = token_record.expires_at.replace(tzinfo=timezone.utc) if token_record.expires_at.tzinfo is None else token_record.expires_at
            if expires_at <= now:
                logger.warning(f"Token {token[:8]}... expired at {token_record.expires_at}")
                return False

            logger.info(f"Token {token[:8]}... is valid")
            return True

    def cleanup_expired_registration_tokens(self) -> int:
        """
        Clean up expired registration tokens.

        Deletes tokens that have expired (past their expires_at time).
        Called by periodic_jobs to prevent token accumulation.

        Returns:
            int: Number of tokens deleted
        """
        now = datetime.now(timezone.utc)

        with self.db_manager.get_session() as session:
            # Find and delete expired tokens
            # SQLite stores naive datetimes, so we compare against naive UTC
            expired_tokens = session.query(RegistrationToken).filter(
                RegistrationToken.expires_at < now.replace(tzinfo=None)
            ).all()

            count = len(expired_tokens)
            if count > 0:
                for token in expired_tokens:
                    session.delete(token)
                session.commit()
                logger.info(f"Cleaned up {count} expired registration tokens")

            return count

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
        logger.info(f"Hostname: {hostname}, Engine ID: {engine_id[:12]}...")

        # Check if token is a permanent token (agent_id for reconnection)
        is_permanent_token = self.validate_permanent_token(token)

        # Validate token (either registration token or permanent token)
        if not is_permanent_token and not self.validate_registration_token(token):
            with self.db_manager.get_session() as session:
                token_record = session.query(RegistrationToken).filter_by(token=token).first()
                if token_record:
                    # Check if token has reached max uses
                    if token_record.is_exhausted:
                        return {"success": False, "error": "Registration token has reached maximum uses"}
                    # SQLite stores datetimes as naive, make it timezone-aware for comparison
                    expires_at = token_record.expires_at.replace(tzinfo=timezone.utc) if token_record.expires_at.tzinfo is None else token_record.expires_at
                    if expires_at <= datetime.now(timezone.utc):
                        return {"success": False, "error": "Registration token has expired"}
                    # Token exists but validation failed for unknown reason
                    return {"success": False, "error": "Invalid registration token"}
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
                    # Update agent runtime info (for binary downloads)
                    if registration_data.get("agent_os"):
                        existing_agent.agent_os = registration_data.get("agent_os")
                    if registration_data.get("agent_arch"):
                        existing_agent.agent_arch = registration_data.get("agent_arch")

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
                        if registration_data.get("host_ip"):
                            host.host_ip = registration_data.get("host_ip")

                    # Capture IDs before commit (for monitor notification)
                    agent_id = existing_agent.id
                    host_id = existing_agent.host_id
                    host_name = host.name if host else hostname

                    session.commit()

                    # Notify monitor to mark host online and broadcast status change
                    logger.info(f"Permanent token reconnection: notifying monitor (monitor={self.monitor is not None})")
                    if self.monitor:
                        self.monitor.add_agent_host(
                            host_id=host_id,
                            name=host_name
                        )
                        logger.info(f"Called add_agent_host for {host_name} ({host_id[:8]}...)")

                    return {
                        "success": True,
                        "agent_id": agent_id,
                        "host_id": host_id,
                        "permanent_token": agent_id
                    }
                else:
                    return {"success": False, "error": "Permanent token does not match engine_id"}

        # Track migration candidates for multi-host scenarios (user must choose)
        migration_candidates = None

        # Check if engine_id already registered as agent
        with self.db_manager.get_session() as session:
            existing_agent = session.query(Agent).filter_by(engine_id=engine_id).first()
            if existing_agent:
                logger.warning(f"Agent registration rejected: engine_id {engine_id[:12]}... already registered. "
                              "This may be a cloned VM with duplicate Docker engine ID. "
                              "Fix: delete /var/lib/docker/engine-id (or /etc/docker/key.json on older systems) and restart Docker to generate a unique engine ID, then reinstall the agent.")
                return {
                    "success": False,
                    "error": "Agent with this engine_id is already registered. "
                            "If this is a cloned VM, delete /var/lib/docker/engine-id (or /etc/docker/key.json on older systems) and restart Docker to generate a unique engine ID, then reinstall the agent."
                }

            # Check for migration: find ALL hosts with matching engine_id
            matching_hosts = session.query(DockerHostDB).filter_by(engine_id=engine_id).all()

            # Separate by connection type
            local_hosts = [h for h in matching_hosts if h.connection_type == 'local']
            remote_hosts = [h for h in matching_hosts if h.connection_type == 'remote' and h.replaced_by_host_id is None]
            already_migrated = [h for h in matching_hosts if h.connection_type == 'remote' and h.replaced_by_host_id is not None]

            # REJECT if any local host matches - local Docker socket is the only way to manage localhost
            if local_hosts:
                host = local_hosts[0]
                logger.warning(f"Migration rejected: Cannot migrate local Docker socket connection to agent. "
                              f"Host '{host.name}' uses local socket - agents are only for remote hosts.")
                return {
                    "success": False,
                    "error": "Migration not supported for local Docker connections. "
                            "Agents are only for remote hosts. "
                            "Local Docker monitoring via socket is the preferred method for localhost."
                }

            # If multiple remote hosts match, don't auto-migrate - user must choose
            if len(remote_hosts) > 1:
                logger.info(f"Multiple remote hosts ({len(remote_hosts)}) share engine_id {engine_id[:12]}... - "
                           "registration will proceed but migration requires user choice")
                # Build candidate list for frontend (extract data while session is open)
                migration_candidates = [
                    {"host_id": h.id, "host_name": h.name}
                    for h in remote_hosts
                ]
                # Don't auto-migrate, continue to register the agent
                # The frontend will show a modal for user to choose which host to migrate from

            # If exactly one remote host matches, auto-migrate
            elif len(remote_hosts) == 1:
                existing_host = remote_hosts[0]
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

            # Log if we found already-migrated hosts
            if already_migrated:
                logger.debug(f"Found {len(already_migrated)} already-migrated host(s) with engine_id {engine_id[:12]}...")

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
                    num_cpus=registration_data.get("num_cpus"),
                    host_ip=registration_data.get("host_ip"),  # For systemd agents only
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
                    registered_at=now,
                    # Agent runtime info (for binary downloads)
                    agent_os=registration_data.get("agent_os"),
                    agent_arch=registration_data.get("agent_arch")
                )
                reg_session.add(agent)
                logger.info(f"Created agent record: {agent_id[:8]}... (os={registration_data.get('agent_os')}, arch={registration_data.get('agent_arch')})")

                # Increment token use count (with locking to prevent TOCTOU race)
                # Use with_for_update() to lock the row - concurrent registrations will wait
                token_record = reg_session.query(RegistrationToken).filter_by(token=token).with_for_update().first()
                if token_record:
                    # Re-check token hasn't reached max uses by concurrent registration
                    if token_record.is_exhausted:
                        reg_session.rollback()
                        return {"success": False, "error": "Registration token has reached maximum uses"}
                    token_record.use_count += 1
                    token_record.last_used_at = now

                # Commit in the dedicated session (context manager will close it)
                reg_session.commit()
                logger.info(f"Successfully registered agent {agent_id[:8]}... (host: {agent_name}, host_id: {host_id[:8]}...)")

                # Notify monitor to add host to in-memory hosts dict
                # This enables immediate container discovery without waiting for refresh
                if self.monitor:
                    self.monitor.add_agent_host(
                        host_id=host_id,
                        name=agent_name,
                        description=None,
                        security_status="unknown"
                    )

                result = {
                    "success": True,
                    "agent_id": agent_id,
                    "host_id": host_id,
                    "permanent_token": agent_id  # Use agent_id as permanent token for reconnection
                }

                # Include migration candidates if user needs to choose
                if migration_candidates:
                    result["migration_candidates"] = migration_candidates
                    result["migration_choice_required"] = True
                    logger.info(f"Agent {agent_id[:8]}... registered with {len(migration_candidates)} migration candidates - user must choose")

                return result

            except IntegrityError as e:
                reg_session.rollback()
                return {"success": False, "error": f"Database integrity error: {str(e)}"}
            except Exception as e:
                reg_session.rollback()
                return {"success": False, "error": f"Registration failed: {str(e)}"}

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
                # Re-query existing_host in THIS session to avoid detached object issues
                existing_host = session.query(DockerHostDB).filter_by(id=existing_host.id).first()
                if not existing_host:
                    return {"success": False, "error": "Migration failed: existing host not found"}

                # Step 1: Rename old host to avoid name collision
                # The old host record is kept for migration tracking but marked inactive
                old_name_backup = existing_host.name
                existing_host.name = f"{existing_host.name} (migrated)"
                session.flush()

                # Step 2: Create new agent host with the original name
                agent_name = old_name_backup
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
                    num_cpus=registration_data.get("num_cpus") or existing_host.num_cpus,
                    host_ip=registration_data.get("host_ip"),  # For systemd agents only
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

                        # Create new record with updated composite key (copy ALL fields)
                        new_ar = AutoRestartConfig(
                            container_id=new_composite,
                            host_id=new_host_id,
                            container_name=ar.container_name,
                            enabled=ar.enabled,
                            max_retries=ar.max_retries,
                            retry_delay=ar.retry_delay,
                            restart_count=ar.restart_count,
                            last_restart=ar.last_restart
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

                        # Create new assignment with updated composite key (copy ALL fields)
                        new_assignment = TagAssignment(
                            tag_id=tag_assignment.tag_id,
                            subject_type='container',
                            subject_id=new_composite,
                            compose_project=tag_assignment.compose_project,
                            compose_service=tag_assignment.compose_service,
                            host_id_at_attach=new_host_id,
                            container_name_at_attach=tag_assignment.container_name_at_attach,
                            last_seen_at=tag_assignment.last_seen_at
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
                            container_name=cu.container_name,
                            current_image=cu.current_image,
                            current_digest=cu.current_digest,
                            current_version=cu.current_version,
                            latest_image=cu.latest_image,
                            latest_digest=cu.latest_digest,
                            latest_version=cu.latest_version,
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
                            container_name=hc.container_name,
                            enabled=hc.enabled,
                            url=hc.url,
                            method=hc.method,
                            expected_status_codes=hc.expected_status_codes,
                            timeout_seconds=hc.timeout_seconds,
                            check_interval_seconds=hc.check_interval_seconds,
                            follow_redirects=hc.follow_redirects,
                            verify_ssl=hc.verify_ssl,
                            check_from=hc.check_from,
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

                # Transfer deployments (must be done BEFORE DeploymentMetadata due to FK)
                # Deployment.id is composite: {host_id}:{deployment_short_id}
                from database import Deployment, DeploymentContainer
                deployments = session.query(Deployment).filter_by(host_id=old_host_id).all()
                deployment_id_map = {}  # Map old deployment_id -> new deployment_id
                for dep in deployments:
                    # Extract deployment short ID from composite key
                    old_dep_id = dep.id
                    if ':' in old_dep_id:
                        _, deployment_short_id = old_dep_id.split(':', 1)
                        new_dep_id = f"{new_host_id}:{deployment_short_id}"
                        deployment_id_map[old_dep_id] = new_dep_id

                        # Create new deployment with updated composite key
                        new_dep = Deployment(
                            id=new_dep_id,
                            host_id=new_host_id,
                            user_id=dep.user_id,
                            stack_name=dep.stack_name,
                            status=dep.status,
                            error_message=dep.error_message,
                            progress_percent=dep.progress_percent,
                            current_stage=dep.current_stage,
                            created_at=dep.created_at,
                            updated_at=dep.updated_at,
                            started_at=dep.started_at,
                            completed_at=dep.completed_at,
                            created_by=dep.created_by,
                            committed=dep.committed,
                            rollback_on_failure=dep.rollback_on_failure
                        )
                        session.add(new_dep)
                        session.flush()  # Ensure new deployment exists for FK references
                        transferred_count += 1

                        # Transfer associated DeploymentContainers (FK references deployment_id)
                        dep_containers = session.query(DeploymentContainer).filter_by(deployment_id=old_dep_id).all()
                        for dc in dep_containers:
                            new_dc = DeploymentContainer(
                                deployment_id=new_dep_id,
                                container_id=dc.container_id,  # Short container ID, no host prefix
                                service_name=dc.service_name,
                                created_at=dc.created_at
                            )
                            session.add(new_dc)
                            session.delete(dc)

                        # Delete old deployment (after containers moved)
                        session.delete(dep)

                # Transfer deployment metadata (tracks which containers were created by deployments)
                from database import DeploymentMetadata
                deployment_metadata = session.query(DeploymentMetadata).filter_by(host_id=old_host_id).all()
                for dm in deployment_metadata:
                    # Extract short container ID from composite key
                    old_composite = dm.container_id
                    if ':' in old_composite:
                        _, short_container_id = old_composite.split(':', 1)
                        new_composite = f"{new_host_id}:{short_container_id}"

                        # Map deployment_id to new ID if it was migrated
                        new_deployment_id = deployment_id_map.get(dm.deployment_id, dm.deployment_id)

                        # Create new record with updated composite key
                        new_dm = DeploymentMetadata(
                            container_id=new_composite,
                            host_id=new_host_id,
                            deployment_id=new_deployment_id,
                            is_managed=dm.is_managed,
                            service_name=dm.service_name
                        )
                        session.add(new_dm)
                        transferred_count += 1

                        # Delete old record
                        session.delete(dm)

                logger.info(f"Transferred {transferred_count} container settings from {old_host_name} to {agent_name}")

                # Step 4: Mark old host as migrated (set replaced_by_host_id and is_active=False)
                existing_host.replaced_by_host_id = new_host_id
                existing_host.is_active = False
                existing_host.updated_at = now
                logger.info(f"Marked old host {old_host_name} as migrated")

                # Step 5: Increment token use count
                token_record = session.query(RegistrationToken).filter_by(token=token).first()
                if token_record:
                    token_record.use_count += 1
                    token_record.last_used_at = now

                # Commit all changes atomically
                session.commit()
                session.refresh(new_host)
                session.refresh(agent)

                logger.info(f"Migration completed successfully: {old_host_name} → {agent_name}")

                # Add new host to monitor's in-memory hosts dict
                # This is critical - without this, the host exists in DB but not in self.hosts,
                # so container discovery will skip it until backend restarts
                if self.monitor:
                    self.monitor.add_agent_host(
                        host_id=new_host_id,
                        name=agent_name
                    )
                    logger.info(f"Added new agent host to monitor: {agent_name} ({new_host_id[:8]}...)")

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

    def migrate_from_host(self, agent_id: str, source_host_id: str) -> dict:
        """
        Migrate settings from an existing mTLS host to an already-registered agent.

        This is used when multiple remote hosts share the same engine_id (cloned VMs)
        and the user needs to choose which host to migrate from.

        Args:
            agent_id: ID of the registered agent
            source_host_id: ID of the source mTLS host to migrate from

        Returns:
            Dict with success status and migration details
        """
        from database import (
            AutoRestartConfig, TagAssignment, ContainerDesiredState,
            ContainerUpdate, ContainerHttpHealthCheck, AlertV2,
            Deployment, DeploymentContainer, DeploymentMetadata
        )

        logger.info(f"Starting delayed migration: source host {source_host_id[:8]}... → agent {agent_id[:8]}...")

        with self.db_manager.get_session() as session:
            try:
                # Find the agent and its host
                agent = session.query(Agent).filter_by(id=agent_id).first()
                if not agent:
                    return {"success": False, "error": "Agent not found"}

                new_host_id = agent.host_id
                new_host = session.query(DockerHostDB).filter_by(id=new_host_id).first()
                if not new_host:
                    return {"success": False, "error": "Agent host not found"}

                # Find the source host
                source_host = session.query(DockerHostDB).filter_by(id=source_host_id).first()
                if not source_host:
                    return {"success": False, "error": "Source host not found"}

                # Validate source host is remote and not already migrated
                if source_host.connection_type != 'remote':
                    return {"success": False, "error": "Source host is not a remote/mTLS host"}
                if source_host.replaced_by_host_id is not None:
                    return {"success": False, "error": "Source host has already been migrated"}

                old_host_id = source_host_id
                old_host_name = source_host.name
                agent_name = new_host.name
                now = datetime.now(timezone.utc)
                transferred_count = 0

                # Transfer auto-restart configs
                auto_restarts = session.query(AutoRestartConfig).filter_by(host_id=old_host_id).all()
                for ar in auto_restarts:
                    old_composite = ar.container_id
                    if ':' in old_composite:
                        _, short_container_id = old_composite.split(':', 1)
                        new_composite = f"{new_host_id}:{short_container_id}"
                        new_ar = AutoRestartConfig(
                            container_id=new_composite,
                            host_id=new_host_id,
                            container_name=ar.container_name,
                            enabled=ar.enabled,
                            max_retries=ar.max_retries,
                            retry_delay=ar.retry_delay,
                            restart_count=ar.restart_count,
                            last_restart=ar.last_restart
                        )
                        session.add(new_ar)
                        session.delete(ar)
                        transferred_count += 1

                # Transfer container tags
                tag_assignments = session.query(TagAssignment).filter(
                    TagAssignment.subject_type == 'container',
                    TagAssignment.subject_id.like(f"{old_host_id}:%")
                ).all()
                for tag_assignment in tag_assignments:
                    old_composite = tag_assignment.subject_id
                    if ':' in old_composite:
                        _, short_container_id = old_composite.split(':', 1)
                        new_composite = f"{new_host_id}:{short_container_id}"
                        new_assignment = TagAssignment(
                            tag_id=tag_assignment.tag_id,
                            subject_type='container',
                            subject_id=new_composite,
                            compose_project=tag_assignment.compose_project,
                            compose_service=tag_assignment.compose_service,
                            host_id_at_attach=new_host_id,
                            container_name_at_attach=tag_assignment.container_name_at_attach,
                            last_seen_at=tag_assignment.last_seen_at
                        )
                        session.add(new_assignment)
                        session.delete(tag_assignment)
                        transferred_count += 1

                # Transfer desired states
                desired_states = session.query(ContainerDesiredState).filter_by(host_id=old_host_id).all()
                for ds in desired_states:
                    old_composite = ds.container_id
                    if ':' in old_composite:
                        _, short_container_id = old_composite.split(':', 1)
                        new_composite = f"{new_host_id}:{short_container_id}"
                        new_ds = ContainerDesiredState(
                            container_id=new_composite,
                            host_id=new_host_id,
                            container_name=ds.container_name,
                            desired_state=ds.desired_state,
                            custom_tags=ds.custom_tags,
                            web_ui_url=ds.web_ui_url
                        )
                        session.add(new_ds)
                        session.delete(ds)
                        transferred_count += 1

                # Transfer container updates
                container_updates = session.query(ContainerUpdate).filter_by(host_id=old_host_id).all()
                for cu in container_updates:
                    old_composite = cu.container_id
                    if ':' in old_composite:
                        _, short_container_id = old_composite.split(':', 1)
                        new_composite = f"{new_host_id}:{short_container_id}"
                        new_cu = ContainerUpdate(
                            container_id=new_composite,
                            host_id=new_host_id,
                            container_name=cu.container_name,
                            current_image=cu.current_image,
                            current_digest=cu.current_digest,
                            current_version=cu.current_version,
                            latest_image=cu.latest_image,
                            latest_digest=cu.latest_digest,
                            latest_version=cu.latest_version,
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
                        session.delete(cu)
                        transferred_count += 1

                # Transfer HTTP health checks
                health_checks = session.query(ContainerHttpHealthCheck).filter_by(host_id=old_host_id).all()
                for hc in health_checks:
                    old_composite = hc.container_id
                    if ':' in old_composite:
                        _, short_container_id = old_composite.split(':', 1)
                        new_composite = f"{new_host_id}:{short_container_id}"
                        new_hc = ContainerHttpHealthCheck(
                            container_id=new_composite,
                            host_id=new_host_id,
                            container_name=hc.container_name,
                            enabled=hc.enabled,
                            url=hc.url,
                            method=hc.method,
                            expected_status_codes=hc.expected_status_codes,
                            timeout_seconds=hc.timeout_seconds,
                            check_interval_seconds=hc.check_interval_seconds,
                            follow_redirects=hc.follow_redirects,
                            verify_ssl=hc.verify_ssl,
                            check_from=hc.check_from,
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
                        session.delete(hc)
                        transferred_count += 1

                # Transfer container alerts
                alerts = session.query(AlertV2).filter(
                    AlertV2.scope_type == 'container',
                    AlertV2.scope_id.like(f"{old_host_id}:%")
                ).all()
                for alert in alerts:
                    old_composite = alert.scope_id
                    if ':' in old_composite:
                        _, short_container_id = old_composite.split(':', 1)
                        new_composite = f"{new_host_id}:{short_container_id}"
                        old_dedup_key = alert.dedup_key
                        new_dedup_key = old_dedup_key.replace(old_composite, new_composite)
                        alert.scope_id = new_composite
                        alert.dedup_key = new_dedup_key
                        transferred_count += 1

                # Transfer deployments
                deployment_id_map = {}
                deployments = session.query(Deployment).filter_by(host_id=old_host_id).all()
                for dep in deployments:
                    old_dep_id = dep.id
                    if ':' in old_dep_id:
                        _, short_dep_id = old_dep_id.split(':', 1)
                        new_dep_id = f"{new_host_id}:{short_dep_id}"
                        deployment_id_map[old_dep_id] = new_dep_id
                        new_dep = Deployment(
                            id=new_dep_id,
                            host_id=new_host_id,
                            user_id=dep.user_id,
                            name=dep.name,
                            compose_content=dep.compose_content,
                            env_content=dep.env_content,
                            status=dep.status,
                            error_message=dep.error_message,
                            created_at=dep.created_at,
                            updated_at=dep.updated_at
                        )
                        session.add(new_dep)

                        # Transfer deployment containers
                        dep_containers = session.query(DeploymentContainer).filter_by(deployment_id=old_dep_id).all()
                        for dc in dep_containers:
                            old_composite = dc.container_id
                            if ':' in old_composite:
                                _, short_container_id = old_composite.split(':', 1)
                                new_composite = f"{new_host_id}:{short_container_id}"
                                new_dc = DeploymentContainer(
                                    deployment_id=new_dep_id,
                                    container_id=new_composite,
                                    service_name=dc.service_name,
                                    created_at=dc.created_at
                                )
                                session.add(new_dc)
                                session.delete(dc)

                        session.delete(dep)
                        transferred_count += 1

                # Transfer deployment metadata
                deployment_metadata = session.query(DeploymentMetadata).filter_by(host_id=old_host_id).all()
                for dm in deployment_metadata:
                    old_composite = dm.container_id
                    if ':' in old_composite:
                        _, short_container_id = old_composite.split(':', 1)
                        new_composite = f"{new_host_id}:{short_container_id}"
                        new_deployment_id = deployment_id_map.get(dm.deployment_id, dm.deployment_id)
                        new_dm = DeploymentMetadata(
                            container_id=new_composite,
                            host_id=new_host_id,
                            deployment_id=new_deployment_id,
                            is_managed=dm.is_managed,
                            service_name=dm.service_name
                        )
                        session.add(new_dm)
                        session.delete(dm)
                        transferred_count += 1

                logger.info(f"Transferred {transferred_count} settings from {old_host_name} to {agent_name}")

                # Mark source host as migrated
                source_host.replaced_by_host_id = new_host_id
                source_host.is_active = False
                source_host.name = f"{source_host.name} (migrated)"
                source_host.updated_at = now
                logger.info(f"Marked source host {old_host_name} as migrated")

                # Commit all changes
                session.commit()
                logger.info(f"Delayed migration completed: {old_host_name} → {agent_name}")

                # Clean up old host from monitor
                if self.monitor:
                    if old_host_id in self.monitor.hosts:
                        del self.monitor.hosts[old_host_id]
                        logger.info(f"Removed old host {old_host_name} from monitor")
                    if old_host_id in self.monitor.clients:
                        try:
                            self.monitor.clients[old_host_id].close()
                        except Exception:
                            pass
                        del self.monitor.clients[old_host_id]

                return {
                    "success": True,
                    "agent_id": agent_id,
                    "host_id": new_host_id,
                    "migrated_from": {
                        "host_id": old_host_id,
                        "host_name": old_host_name
                    },
                    "transferred_count": transferred_count
                }

            except Exception as e:
                session.rollback()
                logger.error(f"Delayed migration failed: {e}", exc_info=True)
                return {"success": False, "error": f"Migration failed: {str(e)}"}
