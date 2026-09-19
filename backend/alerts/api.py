"""
Alert System API Routes for DockMon

Provides REST endpoints for:
- Listing alerts (with filters)
- Getting alert details
- Resolving alerts
- Snoozing alerts
- Adding annotations

Note: Alert rule CRUD is handled in main.py at /api/alerts/rules
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, HTTPException, Depends, Query, status
from pydantic import BaseModel, Field, ConfigDict, field_serializer

from database import DatabaseManager, AlertV2, AlertAnnotation, User, scoped_alert_query
from alerts.capabilities import HOST_METRIC_FIELDS, host_metric_capabilities
from alerts.engine import AlertEngine
from stats_client import get_stats_client
from security.rate_limiting import get_rate_limit_dependency
from auth.api_key_auth import (  # v2 hybrid auth (cookies + API keys)
    get_current_user_or_api_key as get_current_user,
    require_capability,
    get_visible_host_ids_for_auth,
    visible_host_models,
)
from utils.response_filtering import alert_is_visible
from auth.utils import get_auditable_user_info
from security.audit import security_audit

logger = logging.getLogger(__name__)

# Create router with authentication dependency for all routes
router = APIRouter(
    prefix="/api/alerts",
    tags=["alerts"],
    dependencies=[Depends(get_current_user)]  # Require authentication for all endpoints
)


# ==================== Request/Response Models ====================

class AlertResponse(BaseModel):
    """Alert response model"""
    id: str
    dedup_key: str
    scope_type: str
    scope_id: str
    kind: str
    severity: str
    state: str
    title: str
    message: str
    first_seen: datetime
    last_seen: datetime
    occurrences: int
    snoozed_until: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    resolved_reason: Optional[str] = None
    rule_id: Optional[str] = None
    rule_version: Optional[int] = None
    current_value: Optional[float] = None
    threshold: Optional[float] = None
    labels: Optional[Dict[str, str]] = None
    notification_count: int = 0
    host_name: Optional[str] = None
    host_id: Optional[str] = None
    container_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

    @field_serializer('first_seen', 'last_seen', 'snoozed_until', 'resolved_at')
    def serialize_datetime(self, dt: Optional[datetime]) -> Optional[str]:
        """Serialize datetime with 'Z' suffix for UTC - required for correct frontend parsing"""
        if dt is None:
            return None
        return dt.isoformat() + 'Z'


class AlertListResponse(BaseModel):
    """Alert list response"""
    alerts: List[AlertResponse]
    total: int
    page: int
    page_size: int


class ResolveAlertRequest(BaseModel):
    """Request to resolve an alert"""
    reason: Optional[str] = "Manually resolved"


class SnoozeAlertRequest(BaseModel):
    """Request to snooze an alert"""
    duration_minutes: int = Field(ge=1, le=10080)  # 1 minute to 7 days


class AddAnnotationRequest(BaseModel):
    """Request to add annotation to alert"""
    text: str = Field(min_length=1, max_length=5000)


class HostMetricCapability(BaseModel):
    """Host metrics a single host is currently observed to report"""
    host_id: str
    host_name: str
    metrics: List[str]


class MetricCapabilitiesResponse(BaseModel):
    """Per-host metric capability plus the full set of host metrics"""
    hosts: List[HostMetricCapability]
    host_metrics: List[str]


# ==================== Dependencies ====================

def get_db() -> DatabaseManager:
    """Get database manager instance"""
    # Import monitor which has the db instance
    from main import monitor
    return monitor.db


def get_alert_engine(db: DatabaseManager = Depends(get_db)) -> AlertEngine:
    """Get alert engine instance"""
    return AlertEngine(db)


def _require_alert_visible(session, alert_id: str, current_user: dict) -> AlertV2:
    """404 for a missing alert and, identically, for one whose host the caller
    cannot see (no derivable host = hidden)."""
    alert = session.query(AlertV2).filter(AlertV2.id == alert_id).first()
    if alert is None or not alert_is_visible(
        alert.scope_type, alert.scope_id, alert.host_id, get_visible_host_ids_for_auth(current_user)
    ):
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


def _scoped_alert_query(session, current_user: dict):
    return scoped_alert_query(session, get_visible_host_ids_for_auth(current_user))


# ==================== Alert Endpoints ====================

@router.get(
    "/metrics/capabilities",
    response_model=MetricCapabilitiesResponse,
    dependencies=[Depends(get_rate_limit_dependency("alerts")), Depends(require_capability("alerts.view"))],
)
async def get_metric_capabilities(current_user: dict = Depends(get_current_user)):
    """Which host metrics each host is currently observed to report.

    Derived from samples actually arriving and still fresh, never from
    connection type: two agent hosts of the same type differ purely by whether
    /host/proc is mounted. A rule targeting a host with no capability for its
    metric can never fire, so the UI surfaces it instead of accepting silently.
    """
    from main import monitor

    try:
        host_stats = await get_stats_client().get_host_stats()
    except Exception as e:
        logger.warning(f"Could not read host stats for metric capabilities: {e}")
        host_stats = {}

    hosts = visible_host_models(monitor.hosts.values(), get_visible_host_ids_for_auth(current_user))
    capabilities = host_metric_capabilities(host_stats, [h.id for h in hosts])

    return MetricCapabilitiesResponse(
        hosts=[
            HostMetricCapability(
                host_id=host.id,
                host_name=host.name,
                metrics=capabilities.get(host.id, []),
            )
            for host in hosts
        ],
        host_metrics=list(HOST_METRIC_FIELDS),
    )


@router.get("/", response_model=AlertListResponse, dependencies=[Depends(get_rate_limit_dependency("alerts")), Depends(require_capability("alerts.view"))])
async def list_alerts(
    state: Optional[str] = Query(None, pattern="^(open|snoozed|resolved)$"),
    severity: Optional[str] = Query(None, pattern="^(info|warning|error|critical)$"),
    scope_type: Optional[str] = Query(None, pattern="^(host|container)$"),
    scope_id: Optional[str] = None,
    rule_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db)
):
    """
    List alerts with optional filters

    Filters:
    - state: Filter by alert state (open, snoozed, resolved)
    - severity: Filter by severity (info, warning, error, critical)
    - scope_type: Filter by scope type (host, container, group)
    - scope_id: Filter by specific scope ID
    - rule_id: Filter by rule that created the alert
    """
    with db.get_session() as session:
        query = _scoped_alert_query(session, current_user)

        # Apply filters
        if state:
            query = query.filter(AlertV2.state == state)
        if severity:
            query = query.filter(AlertV2.severity == severity)
        if scope_type:
            query = query.filter(AlertV2.scope_type == scope_type)
        if scope_id:
            query = query.filter(AlertV2.scope_id == scope_id)
        if rule_id:
            query = query.filter(AlertV2.rule_id == rule_id)

        # Get total count
        total = query.count()

        # Apply pagination
        offset = (page - 1) * page_size
        alerts = query.order_by(AlertV2.last_seen.desc()).offset(offset).limit(page_size).all()

        # Convert to response models
        alert_responses = []
        for alert in alerts:
            labels = json.loads(alert.labels_json) if alert.labels_json else None

            alert_responses.append(AlertResponse(
                **{k: v for k, v in alert.__dict__.items() if not k.startswith('_')},
                labels=labels
            ))

        return AlertListResponse(
            alerts=alert_responses,
            total=total,
            page=page,
            page_size=page_size
        )


@router.get("/{alert_id}", response_model=AlertResponse, dependencies=[Depends(get_rate_limit_dependency("alerts")), Depends(require_capability("alerts.view"))])
async def get_alert(
    alert_id: str,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get alert details by ID"""
    with db.get_session() as session:
        alert = _require_alert_visible(session, alert_id, current_user)

        labels = json.loads(alert.labels_json) if alert.labels_json else None

        return AlertResponse(
            **{k: v for k, v in alert.__dict__.items() if not k.startswith('_')},
            labels=labels
        )


@router.post("/{alert_id}/resolve", response_model=AlertResponse, dependencies=[Depends(get_rate_limit_dependency("alerts_write")), Depends(require_capability("alerts.manage"))])
async def resolve_alert(
    alert_id: str,
    request: ResolveAlertRequest,
    db: DatabaseManager = Depends(get_db),
    engine: AlertEngine = Depends(get_alert_engine),
    current_user: dict = Depends(get_current_user)
):
    """Manually resolve an alert"""
    user_id, display_name = get_auditable_user_info(current_user)
    with db.get_session() as session:
        alert = _require_alert_visible(session, alert_id, current_user)

        if alert.state == "resolved":
            raise HTTPException(status_code=400, detail="Alert already resolved")

        # Manual resolves are silent: the user who clicked already knows.
        alert = engine._resolve_alert(alert, request.reason, notify=False)

        security_audit.log_event(
            event_type="alert_resolved",
            severity="info",
            user_id=user_id,
            details={
                "alert_id": alert_id,
                "reason": request.reason,
                "display_name": display_name,
            },
        )

        labels = json.loads(alert.labels_json) if alert.labels_json else None
        return AlertResponse(
            **{k: v for k, v in alert.__dict__.items() if not k.startswith('_')},
            labels=labels
        )


@router.post("/{alert_id}/snooze", response_model=AlertResponse, dependencies=[Depends(get_rate_limit_dependency("alerts_write")), Depends(require_capability("alerts.manage"))])
async def snooze_alert(
    alert_id: str,
    request: SnoozeAlertRequest,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Snooze an alert for a specified duration"""
    user_id, display_name = get_auditable_user_info(current_user)
    with db.get_session() as session:
        alert = _require_alert_visible(session, alert_id, current_user)

        if alert.state == "resolved":
            raise HTTPException(status_code=400, detail="Cannot snooze resolved alert")

        # Snooze the alert
        alert.state = "snoozed"
        alert.snoozed_until = datetime.now(timezone.utc) + timedelta(minutes=request.duration_minutes)
        session.commit()

        security_audit.log_event(
            event_type="alert_snoozed",
            severity="info",
            user_id=user_id,
            details={
                "alert_id": alert_id,
                "duration_minutes": request.duration_minutes,
                "display_name": display_name,
            },
        )

        labels = json.loads(alert.labels_json) if alert.labels_json else None
        return AlertResponse(
            **{k: v for k, v in alert.__dict__.items() if not k.startswith('_')},
            labels=labels
        )


@router.post("/{alert_id}/unsnooze", response_model=AlertResponse, dependencies=[Depends(get_rate_limit_dependency("alerts_write")), Depends(require_capability("alerts.manage"))])
async def unsnooze_alert(
    alert_id: str,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Unsnooze an alert"""
    user_id, display_name = get_auditable_user_info(current_user)
    with db.get_session() as session:
        alert = _require_alert_visible(session, alert_id, current_user)

        if alert.state != "snoozed":
            raise HTTPException(status_code=400, detail="Alert is not snoozed")

        # Unsnooze the alert
        alert.state = "open"
        alert.snoozed_until = None
        session.commit()

        security_audit.log_event(
            event_type="alert_unsnoozed",
            severity="info",
            user_id=user_id,
            details={
                "alert_id": alert_id,
                "display_name": display_name,
            },
        )

        labels = json.loads(alert.labels_json) if alert.labels_json else None
        return AlertResponse(
            **{k: v for k, v in alert.__dict__.items() if not k.startswith('_')},
            labels=labels
        )


@router.post("/{alert_id}/annotations", dependencies=[Depends(get_rate_limit_dependency("alerts_write")), Depends(require_capability("alerts.manage"))])
async def add_annotation(
    alert_id: str,
    request: AddAnnotationRequest,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Add an annotation; author is auto-derived from current_user."""
    user_id, display_name = get_auditable_user_info(current_user)

    if current_user.get("auth_type") == "api_key":
        author = display_name  # 'API Key: <name>' from get_auditable_user_info
    else:
        author = current_user.get("username")

    with db.get_session() as session:
        alert = _require_alert_visible(session, alert_id, current_user)

        annotation = AlertAnnotation(
            alert_id=alert_id,
            timestamp=datetime.now(timezone.utc),
            user=author,
            text=request.text,
        )
        session.add(annotation)
        session.commit()

        security_audit.log_event(
            event_type="alert_annotated",
            severity="info",
            user_id=user_id,
            details={
                "alert_id": alert_id,
                "display_name": display_name,
            },
        )

        return {"status": "success", "annotation_id": annotation.id}


@router.get("/{alert_id}/annotations", dependencies=[Depends(get_rate_limit_dependency("alerts")), Depends(require_capability("alerts.view"))])
async def get_annotations(
    alert_id: str,
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """List annotations; resolves stored usernames to current display names."""
    with db.get_session() as session:
        _require_alert_visible(session, alert_id, current_user)

        annotations = session.query(AlertAnnotation).filter(
            AlertAnnotation.alert_id == alert_id,
        ).order_by(AlertAnnotation.timestamp.desc()).all()

        # API-key markers ("API Key: <name>") share the column with usernames;
        # exclude them from the User lookup so attribution stays unambiguous
        # even if username validation rules are relaxed later.
        usernames = {a.user for a in annotations if a.user and not a.user.startswith("API Key: ")}
        display_by_username: dict[str, str] = {}
        if usernames:
            users = session.query(User).filter(User.username.in_(usernames)).all()
            display_by_username = {u.username: u.effective_display_name for u in users}

        return {
            "annotations": [
                {
                    "id": ann.id,
                    "timestamp": ann.timestamp.isoformat() + 'Z' if ann.timestamp else None,
                    "user": display_by_username.get(ann.user, ann.user),
                    "text": ann.text,
                }
                for ann in annotations
            ]
        }


# ==================== Statistics ====================

@router.get("/stats/", dependencies=[Depends(get_rate_limit_dependency("alerts")), Depends(require_capability("alerts.view"))])
async def get_alert_stats(
    db: DatabaseManager = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get alert statistics"""
    with db.get_session() as session:
        scoped = _scoped_alert_query(session, current_user)
        total = scoped.count()
        open_count = scoped.filter(AlertV2.state == "open").count()
        snoozed_count = scoped.filter(AlertV2.state == "snoozed").count()
        resolved_count = scoped.filter(AlertV2.state == "resolved").count()

        # Count by severity (open only)
        critical = scoped.filter(
            AlertV2.state == "open",
            AlertV2.severity == "critical"
        ).count()
        error = scoped.filter(
            AlertV2.state == "open",
            AlertV2.severity == "error"
        ).count()
        warning = scoped.filter(
            AlertV2.state == "open",
            AlertV2.severity == "warning"
        ).count()

        return {
            "total": total,
            "by_state": {
                "open": open_count,
                "snoozed": snoozed_count,
                "resolved": resolved_count
            },
            "by_severity": {
                "critical": critical,
                "error": error,
                "warning": warning
            }
        }
