"""
Batch Job Manager for DockMon
Handles bulk operations on containers with rate limiting and progress tracking
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Optional, Callable
from collections import defaultdict

from database import DatabaseManager, BatchJob, BatchJobItem
from websocket.connection import ConnectionManager

logger = logging.getLogger(__name__)


class BatchJobManager:
    """Manages batch operations on containers"""

    def __init__(self, db: DatabaseManager, monitor, ws_manager: ConnectionManager):
        self.db = db
        self.monitor = monitor  # DockerMonitor instance
        self.ws_manager = ws_manager
        self.active_jobs: Dict[str, asyncio.Task] = {}
        self.host_semaphores: Dict[str, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(5))

    async def create_job(
        self,
        user_id: Optional[int],
        scope: str,
        action: str,
        container_ids: List[str],
        params: Optional[Dict] = None
    ) -> str:
        """
        Create a new batch job

        Args:
            user_id: ID of user creating the job
            scope: 'container' only for now
            action: 'start', 'stop', or 'restart'
            container_ids: List of container IDs to operate on
            params: Optional action parameters

        Returns:
            job_id: Unique job identifier
        """
        job_id = f"job_{uuid.uuid4().hex[:12]}"

        # Get container details from monitor
        all_containers = await self.monitor.get_containers()
        # Use composite keys {host_id}:{container_id} for multi-host support (cloned VMs)
        container_map = {f"{c.host_id}:{c.short_id}": c for c in all_containers}

        # Create job record
        with self.db.get_session() as session:
            job = BatchJob(
                id=job_id,
                user_id=user_id,
                scope=scope,
                action=action,
                params=json.dumps(params) if params else None,
                status='queued',
                total_items=len(container_ids)
            )
            session.add(job)

            # Create job items
            for container_id in container_ids:
                container = container_map.get(container_id)
                if not container:
                    logger.warning(f"Container {container_id} not found, skipping")
                    continue

                item = BatchJobItem(
                    job_id=job_id,
                    container_id=container.short_id,  # Use short_id for consistency
                    container_name=container.name,
                    host_id=container.host_id,
                    host_name=container.host_name,
                    status='queued'
                )
                session.add(item)

            session.commit()
            logger.info(f"Created batch job {job_id} with {len(container_ids)} items: {action}")

        # Start processing the job in background
        task = asyncio.create_task(self._process_job(job_id))
        self.active_jobs[job_id] = task

        return job_id

    async def _process_job(self, job_id: str):
        """Process a batch job in the background"""
        try:
            # Update job status to running
            with self.db.get_session() as session:
                from sqlalchemy.orm import joinedload
                job = session.query(BatchJob).options(joinedload(BatchJob.items)).filter_by(id=job_id).first()
                if not job:
                    logger.error(f"Job {job_id} not found")
                    return

                job.status = 'running'
                job.started_at = datetime.now(timezone.utc)
                session.commit()

                # Use the eagerly loaded items relationship (no N+1 query)
                items_list = [(item.id, item.container_id, item.container_name, item.host_id, item.status)
                             for item in job.items]

            # Broadcast job started
            await self._broadcast_job_update(job_id, 'running', None)

            # Process items with rate limiting per host
            tasks = []
            for item_id, container_id, container_name, host_id, status in items_list:
                if status != 'queued':
                    continue  # Skip already processed items
                task = asyncio.create_task(
                    self._process_item(job_id, item_id, container_id, container_name, host_id)
                )
                tasks.append(task)

            # Wait for all items to complete
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

            # Update final job status
            # Extract status and close session BEFORE WebSocket broadcast
            final_status = None
            with self.db.get_session() as session:
                job = session.query(BatchJob).filter_by(id=job_id).first()
                if job:
                    job.completed_at = datetime.now(timezone.utc)

                    # Determine final status
                    if job.error_items > 0 and job.success_items > 0:
                        job.status = 'partial'
                    elif job.error_items > 0:
                        job.status = 'failed'
                    else:
                        job.status = 'completed'

                    final_status = job.status
                    session.commit()

            # Session is now closed - safe for WebSocket broadcast
            if final_status:
                await self._broadcast_job_update(job_id, final_status, None)
                logger.info(f"Job {job_id} completed: {final_status}")

        except Exception as e:
            logger.error(f"Error processing job {job_id}: {e}")
            with self.db.get_session() as session:
                job = session.query(BatchJob).filter_by(id=job_id).first()
                if job:
                    job.status = 'failed'
                    job.completed_at = datetime.now(timezone.utc)
                    session.commit()
        finally:
            # Clean up
            if job_id in self.active_jobs:
                del self.active_jobs[job_id]

    async def _process_item(
        self,
        job_id: str,
        item_id: int,
        container_id: str,
        container_name: str,
        host_id: str
    ):
        """Process a single batch job item with rate limiting"""
        # Acquire semaphore for this host (max 5 concurrent ops per host)
        async with self.host_semaphores[host_id]:
            try:
                # Update item status to running
                with self.db.get_session() as session:
                    item = session.query(BatchJobItem).filter_by(id=item_id).first()
                    if item:
                        item.status = 'running'
                        item.started_at = datetime.now(timezone.utc)
                        session.commit()

                # Broadcast item update
                await self._broadcast_item_update(job_id, item_id, 'running', None)

                # Get job action and params
                with self.db.get_session() as session:
                    job = session.query(BatchJob).filter_by(id=job_id).first()
                    if not job:
                        raise Exception("Job not found")
                    action = job.action
                    # Parse params if they exist (JSON format)
                    params = json.loads(job.params) if job.params else None

                # Execute the action
                result = await self._execute_action(action, host_id, container_id, container_name, params)

                # Update item with result
                with self.db.get_session() as session:
                    item = session.query(BatchJobItem).filter_by(id=item_id).first()
                    job = session.query(BatchJob).filter_by(id=job_id).first()

                    if item and job:
                        item.status = result['status']
                        item.message = result['message']
                        item.completed_at = datetime.now(timezone.utc)

                        # Update job counters
                        job.completed_items += 1
                        if result['status'] == 'success':
                            job.success_items += 1
                        elif result['status'] == 'error':
                            job.error_items += 1
                        elif result['status'] == 'skipped':
                            job.skipped_items += 1

                        session.commit()

                # Broadcast item completion
                await self._broadcast_item_update(job_id, item_id, result['status'], result['message'])

            except Exception as e:
                logger.error(f"Error processing item {item_id}: {e}")

                # Mark item as error
                with self.db.get_session() as session:
                    item = session.query(BatchJobItem).filter_by(id=item_id).first()
                    job = session.query(BatchJob).filter_by(id=job_id).first()

                    if item and job:
                        item.status = 'error'
                        item.message = str(e)
                        item.completed_at = datetime.now(timezone.utc)
                        job.completed_items += 1
                        job.error_items += 1
                        session.commit()

                await self._broadcast_item_update(job_id, item_id, 'error', str(e))

    async def _execute_action(
        self,
        action: str,
        host_id: str,
        container_id: str,
        container_name: str,
        params: Optional[Dict] = None
    ) -> Dict[str, str]:
        """
        Execute a container action

        Returns:
            Dict with 'status' ('success', 'error', 'skipped') and 'message'
        """
        try:
            # Normalize to short ID (12 chars) for consistency across the system
            short_id = container_id[:12] if len(container_id) > 12 else container_id

            # Get current container state
            containers = await self.monitor.get_containers(host_id)
            container = next((c for c in containers if c.short_id == container_id), None)

            if not container:
                return {
                    'status': 'error',
                    'message': 'Container not found'
                }

            # Check if action is needed (idempotency)
            if action == 'start':
                if container.state == 'running':
                    return {
                        'status': 'skipped',
                        'message': 'Already running'
                    }
            elif action == 'stop':
                if container.state in ['exited', 'stopped', 'created']:
                    return {
                        'status': 'skipped',
                        'message': 'Already stopped'
                    }

            # Execute the action via monitor (using short_id for consistency)
            if action == 'start':
                await self.monitor.start_container(host_id, short_id)
                message = 'Started successfully'
            elif action == 'stop':
                await self.monitor.stop_container(host_id, short_id)
                message = 'Stopped successfully'
            elif action == 'restart':
                await self.monitor.restart_container(host_id, short_id)
                message = 'Restarted successfully'
            elif action == 'add-tags' or action == 'remove-tags':
                # Tag operations require params
                if not params or 'tags' not in params:
                    return {
                        'status': 'error',
                        'message': 'Missing tags parameter'
                    }

                tags = params['tags']
                tags_to_add = tags if action == 'add-tags' else []
                tags_to_remove = tags if action == 'remove-tags' else []

                result = self.monitor.update_container_tags(
                    host_id,
                    short_id,
                    container_name,
                    tags_to_add,
                    tags_to_remove
                )

                tag_count = len(tags)
                tag_text = f"{tag_count} tag{'s' if tag_count != 1 else ''}"
                action_text = 'Added' if action == 'add-tags' else 'Removed'
                message = f'{action_text} {tag_text}'
            elif action == 'set-auto-restart':
                # Auto-restart requires params
                if not params or 'enabled' not in params:
                    return {
                        'status': 'error',
                        'message': 'Missing enabled parameter'
                    }

                enabled = params['enabled']
                self.monitor.update_container_auto_restart(
                    host_id,
                    short_id,
                    container_name,
                    enabled
                )
                message = f"Auto-restart {'enabled' if enabled else 'disabled'}"
            elif action == 'set-auto-update':
                # Auto-update requires params
                if not params or 'enabled' not in params:
                    return {
                        'status': 'error',
                        'message': 'Missing enabled parameter'
                    }

                enabled = params['enabled']
                floating_tag_mode = params.get('floating_tag_mode', 'exact')

                # Validate floating_tag_mode
                if floating_tag_mode not in ['exact', 'minor', 'major', 'latest']:
                    return {
                        'status': 'error',
                        'message': f'Invalid floating_tag_mode: {floating_tag_mode}'
                    }

                self.monitor.update_container_auto_update(
                    host_id,
                    short_id,
                    container_name,
                    enabled,
                    floating_tag_mode
                )
                mode_text = f" ({floating_tag_mode} mode)" if enabled else ""
                message = f"Auto-update {'enabled' if enabled else 'disabled'}{mode_text}"
            elif action == 'set-desired-state':
                # Desired state requires params
                if not params or 'desired_state' not in params:
                    return {
                        'status': 'error',
                        'message': 'Missing desired_state parameter'
                    }

                desired_state = params['desired_state']
                if desired_state not in ['should_run', 'on_demand', 'unspecified']:
                    return {
                        'status': 'error',
                        'message': f'Invalid desired_state: {desired_state}'
                    }

                self.monitor.update_container_desired_state(
                    host_id,
                    short_id,
                    container_name,
                    desired_state
                )
                state_text = 'Should Run' if desired_state == 'should_run' else 'On-Demand'
                message = f"Desired state set to {state_text}"
            else:
                return {
                    'status': 'error',
                    'message': f'Unknown action: {action}'
                }

            return {
                'status': 'success',
                'message': message
            }

        except Exception as e:
            logger.error(f"Error executing {action} on {container_name}: {e}")
            return {
                'status': 'error',
                'message': str(e)
            }

    async def _broadcast_job_update(self, job_id: str, status: str, message: Optional[str]):
        """Broadcast job status update via WebSocket"""
        logger.info(f"Broadcasting job update: {job_id} - {status}")

        # Get job details to include progress counters
        # Extract data and close session BEFORE WebSocket broadcast
        job_data = None
        with self.db.get_session() as session:
            job = session.query(BatchJob).filter_by(id=job_id).first()
            if job:
                job_data = {
                    'job_id': job_id,
                    'status': status,
                    'message': message,
                    'total_items': job.total_items,
                    'completed_items': job.completed_items,
                    'success_items': job.success_items,
                    'error_items': job.error_items,
                    'skipped_items': job.skipped_items,
                    'created_at': job.created_at.isoformat() + 'Z' if job.created_at else None,
                    'started_at': job.started_at.isoformat() + 'Z' if job.started_at else None,
                    'completed_at': job.completed_at.isoformat() + 'Z' if job.completed_at else None,
                }

        # Session is now closed - safe for WebSocket broadcast
        if job_data:
            await self.ws_manager.broadcast({
                'type': 'batch_job_update',
                'data': job_data
            })
        else:
            # Fallback if job not found
            await self.ws_manager.broadcast({
                'type': 'batch_job_update',
                'data': {
                    'job_id': job_id,
                    'status': status,
                    'message': message
                }
            })

    async def _broadcast_item_update(
        self,
        job_id: str,
        item_id: int,
        status: str,
        message: Optional[str]
    ):
        """Broadcast item status update via WebSocket"""
        logger.info(f"Broadcasting item update: {job_id} item {item_id} - {status}")
        await self.ws_manager.broadcast({
            'type': 'batch_item_update',
            'data': {
                'job_id': job_id,
                'item_id': item_id,
                'status': status,
                'message': message
            }
        })

    def get_job_status(self, job_id: str) -> Optional[Dict]:
        """Get current status of a batch job"""
        with self.db.get_session() as session:
            from sqlalchemy.orm import joinedload
            job = session.query(BatchJob).options(joinedload(BatchJob.items)).filter_by(id=job_id).first()
            if not job:
                return None

            items = job.items  # Use eagerly loaded relationship

            return {
                'id': job.id,
                'scope': job.scope,
                'action': job.action,
                'status': job.status,
                'total_items': job.total_items,
                'completed_items': job.completed_items,
                'success_items': job.success_items,
                'error_items': job.error_items,
                'skipped_items': job.skipped_items,
                'created_at': job.created_at.isoformat() + 'Z' if job.created_at else None,
                'started_at': job.started_at.isoformat() + 'Z' if job.started_at else None,
                'completed_at': job.completed_at.isoformat() + 'Z' if job.completed_at else None,
                'items': [
                    {
                        'id': item.id,
                        'container_id': item.container_id,
                        'container_name': item.container_name,
                        'host_id': item.host_id,
                        'host_name': item.host_name,
                        'status': item.status,
                        'message': item.message,
                        'started_at': item.started_at.isoformat() + 'Z' if item.started_at else None,
                        'completed_at': item.completed_at.isoformat() + 'Z' if item.completed_at else None
                    }
                    for item in items
                ]
            }
