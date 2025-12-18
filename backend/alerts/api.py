"""
Alert System API Routes for DockMon

Provides REST endpoints for:
- Listing alerts (with filters)
- Getting alert details
- Resolving alerts
- Snoozing alerts
- Adding annotations
- Managing alert rules (CRUD)
"""

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, HTTPException, Depends, Query, status
from pydantic import BaseModel, Field, ConfigDict

from database import DatabaseManager, AlertV2, AlertRuleV2, AlertAnnotation
from alerts.validator import AlertRuleValidator, AlertRuleValidationError
from alerts.engine import AlertEngine
from security.rate_limiting import get_rate_limit_dependency
from auth.api_key_auth import get_current_user_or_api_key as get_current_user, require_scope  # v2 hybrid auth (cookies + API keys)

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
    user: Optional[str] = None


class AlertRuleRequest(BaseModel):
    """Request to create/update alert rule"""
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    scope: str = Field(pattern="^(host|container)$")
    kind: str = Field(min_length=1, max_length=100)
    enabled: bool = True

    # Selectors
    host_selector: Optional[Dict[str, Any]] = None
    container_selector: Optional[Dict[str, Any]] = None
    labels: Optional[Dict[str, str]] = None

    # Conditions (for metric-driven rules)
    metric: Optional[str] = None
    operator: Optional[str] = Field(None, pattern="^(>=|<=|==|>|<|!=)$")
    threshold: Optional[float] = None
    occurrences: Optional[int] = Field(None, ge=1, le=100)

    # Clearing (for metric-driven rules)
    clear_threshold: Optional[float] = None

    # Alert timing
    alert_active_delay_seconds: int = Field(default=0, ge=0, le=86400)
    alert_clear_delay_seconds: int = Field(default=0, ge=0, le=86400)

    # Notification timing
    notification_active_delay_seconds: int = Field(default=0, ge=0, le=86400)
    notification_cooldown_seconds: int = Field(default=300, ge=0, le=86400)

    # Behavior
    severity: str = Field(pattern="^(info|warning|error|critical)$")
    grace_seconds: int = Field(default=300, ge=0, le=3600)
    depends_on: Optional[List[str]] = None

    # Notifications
    notify_channels: Optional[List[str]] = None


class AlertRuleResponse(BaseModel):
    """Alert rule response model"""
    id: str
    name: str
    description: Optional[str]
    scope: str
    kind: str
    enabled: bool
    severity: str
    metric: Optional[str]
    threshold: Optional[float]
    operator: Optional[str]
    occurrences: Optional[int]
    clear_threshold: Optional[float]

    # Timing fields
    alert_active_delay_seconds: int
    alert_clear_delay_seconds: int
    notification_active_delay_seconds: int
    notification_cooldown_seconds: int

    grace_seconds: int
    created_at: datetime
    updated_at: datetime
    version: int

    model_config = ConfigDict(from_attributes=True)


# ==================== Dependencies ====================

def get_db() -> DatabaseManager:
    """Get database manager instance"""
    # Import monitor which has the db instance
    from main import monitor
    return monitor.db


def get_alert_engine(db: DatabaseManager = Depends(get_db)) -> AlertEngine:
    """Get alert engine instance"""
    return AlertEngine(db)


def get_rule_validator() -> AlertRuleValidator:
    """Get rule validator instance"""
    return AlertRuleValidator()


# ==================== Alert Endpoints ====================

@router.get("/", response_model=AlertListResponse, dependencies=[Depends(get_rate_limit_dependency("alerts"))])
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
        query = session.query(AlertV2)

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


@router.get("/{alert_id}", response_model=AlertResponse, dependencies=[Depends(get_rate_limit_dependency("alerts"))])
async def get_alert(
    alert_id: str,
    db: DatabaseManager = Depends(get_db)
):
    """Get alert details by ID"""
    with db.get_session() as session:
        alert = session.query(AlertV2).filter(AlertV2.id == alert_id).first()

        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")

        labels = json.loads(alert.labels_json) if alert.labels_json else None

        return AlertResponse(
            **{k: v for k, v in alert.__dict__.items() if not k.startswith('_')},
            labels=labels
        )


@router.post("/{alert_id}/resolve", response_model=AlertResponse, dependencies=[Depends(get_rate_limit_dependency("alerts_write")), Depends(require_scope("write"))])
async def resolve_alert(
    alert_id: str,
    request: ResolveAlertRequest,
    db: DatabaseManager = Depends(get_db),
    engine: AlertEngine = Depends(get_alert_engine)
):
    """Manually resolve an alert"""
    with db.get_session() as session:
        alert = session.query(AlertV2).filter(AlertV2.id == alert_id).first()

        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")

        if alert.state == "resolved":
            raise HTTPException(status_code=400, detail="Alert already resolved")

        # Resolve the alert
        alert = engine._resolve_alert(alert, request.reason)

        labels = json.loads(alert.labels_json) if alert.labels_json else None
        return AlertResponse(
            **{k: v for k, v in alert.__dict__.items() if not k.startswith('_')},
            labels=labels
        )


@router.post("/{alert_id}/snooze", response_model=AlertResponse, dependencies=[Depends(get_rate_limit_dependency("alerts_write")), Depends(require_scope("write"))])
async def snooze_alert(
    alert_id: str,
    request: SnoozeAlertRequest,
    db: DatabaseManager = Depends(get_db)
):
    """Snooze an alert for a specified duration"""
    with db.get_session() as session:
        alert = session.query(AlertV2).filter(AlertV2.id == alert_id).first()

        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")

        if alert.state == "resolved":
            raise HTTPException(status_code=400, detail="Cannot snooze resolved alert")

        # Snooze the alert
        alert.state = "snoozed"
        alert.snoozed_until = datetime.now(timezone.utc) + timedelta(minutes=request.duration_minutes)
        session.commit()

        labels = json.loads(alert.labels_json) if alert.labels_json else None
        return AlertResponse(
            **{k: v for k, v in alert.__dict__.items() if not k.startswith('_')},
            labels=labels
        )


@router.post("/{alert_id}/unsnooze", response_model=AlertResponse, dependencies=[Depends(get_rate_limit_dependency("alerts_write")), Depends(require_scope("write"))])
async def unsnooze_alert(
    alert_id: str,
    db: DatabaseManager = Depends(get_db)
):
    """Unsnooze an alert"""
    with db.get_session() as session:
        alert = session.query(AlertV2).filter(AlertV2.id == alert_id).first()

        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")

        if alert.state != "snoozed":
            raise HTTPException(status_code=400, detail="Alert is not snoozed")

        # Unsnooze the alert
        alert.state = "open"
        alert.snoozed_until = None
        session.commit()

        labels = json.loads(alert.labels_json) if alert.labels_json else None
        return AlertResponse(
            **{k: v for k, v in alert.__dict__.items() if not k.startswith('_')},
            labels=labels
        )


@router.post("/{alert_id}/annotations", dependencies=[Depends(get_rate_limit_dependency("alerts_write")), Depends(require_scope("write"))])
async def add_annotation(
    alert_id: str,
    request: AddAnnotationRequest,
    db: DatabaseManager = Depends(get_db)
):
    """Add an annotation to an alert"""
    with db.get_session() as session:
        alert = session.query(AlertV2).filter(AlertV2.id == alert_id).first()

        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")

        # Create annotation
        annotation = AlertAnnotation(
            alert_id=alert_id,
            timestamp=datetime.now(timezone.utc),
            user=request.user,
            text=request.text
        )

        session.add(annotation)
        session.commit()

        return {"status": "success", "annotation_id": annotation.id}


@router.get("/{alert_id}/annotations", dependencies=[Depends(get_rate_limit_dependency("alerts"))])
async def get_annotations(
    alert_id: str,
    db: DatabaseManager = Depends(get_db)
):
    """Get annotations for an alert"""
    with db.get_session() as session:
        alert = session.query(AlertV2).filter(AlertV2.id == alert_id).first()

        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")

        annotations = session.query(AlertAnnotation).filter(
            AlertAnnotation.alert_id == alert_id
        ).order_by(AlertAnnotation.timestamp.desc()).all()

        return {
            "annotations": [
                {
                    "id": ann.id,
                    "timestamp": ann.timestamp,
                    "user": ann.user,
                    "text": ann.text
                }
                for ann in annotations
            ]
        }


# ==================== Rule Endpoints ====================

@router.get("/rules/", dependencies=[Depends(get_rate_limit_dependency("rules"))])
async def list_rules(
    enabled: Optional[bool] = None,
    scope: Optional[str] = Query(None, pattern="^(host|container)$"),
    db: DatabaseManager = Depends(get_db)
):
    """List all alert rules"""
    with db.get_session() as session:
        query = session.query(AlertRuleV2)

        if enabled is not None:
            query = query.filter(AlertRuleV2.enabled == enabled)
        if scope:
            query = query.filter(AlertRuleV2.scope == scope)

        rules = query.order_by(AlertRuleV2.name).all()

        return {
            "rules": [
                AlertRuleResponse(**{k: v for k, v in rule.__dict__.items() if not k.startswith('_')})
                for rule in rules
            ]
        }


@router.post("/rules/", response_model=AlertRuleResponse, dependencies=[Depends(get_rate_limit_dependency("rules_write")), Depends(require_scope("admin"))])
async def create_rule(
    request: AlertRuleRequest,
    db: DatabaseManager = Depends(get_db),
    validator: AlertRuleValidator = Depends(get_rule_validator)
):
    """Create a new alert rule"""
    # Validate rule
    rule_data = request.dict()
    try:
        validator.validate_rule(rule_data)
    except AlertRuleValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Create rule
    with db.get_session() as session:
        rule = AlertRuleV2(
            id=str(uuid.uuid4()),
            name=request.name,
            description=request.description,
            scope=request.scope,
            kind=request.kind,
            enabled=request.enabled,
            host_selector_json=json.dumps(request.host_selector) if request.host_selector else None,
            container_selector_json=json.dumps(request.container_selector) if request.container_selector else None,
            labels_json=json.dumps(request.labels) if request.labels else None,
            metric=request.metric,
            operator=request.operator,
            threshold=request.threshold,
            occurrences=request.occurrences,
            clear_threshold=request.clear_threshold,
            # Timing fields
            alert_active_delay_seconds=request.alert_active_delay_seconds,
            alert_clear_delay_seconds=request.alert_clear_delay_seconds,
            notification_active_delay_seconds=request.notification_active_delay_seconds,
            notification_cooldown_seconds=request.notification_cooldown_seconds,
            severity=request.severity,
            grace_seconds=request.grace_seconds,
            depends_on_json=json.dumps(request.depends_on) if request.depends_on else None,
            notify_channels_json=json.dumps(request.notify_channels) if request.notify_channels else None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            version=1
        )

        session.add(rule)
        session.commit()
        session.refresh(rule)

        return AlertRuleResponse(**{k: v for k, v in rule.__dict__.items() if not k.startswith('_')})


@router.get("/rules/{rule_id}", response_model=AlertRuleResponse, dependencies=[Depends(get_rate_limit_dependency("rules"))])
async def get_rule(
    rule_id: str,
    db: DatabaseManager = Depends(get_db)
):
    """Get alert rule by ID"""
    with db.get_session() as session:
        rule = session.query(AlertRuleV2).filter(AlertRuleV2.id == rule_id).first()

        if not rule:
            raise HTTPException(status_code=404, detail="Rule not found")

        return AlertRuleResponse(**{k: v for k, v in rule.__dict__.items() if not k.startswith('_')})


@router.put("/rules/{rule_id}", response_model=AlertRuleResponse, dependencies=[Depends(get_rate_limit_dependency("rules_write")), Depends(require_scope("admin"))])
async def update_rule(
    rule_id: str,
    request: AlertRuleRequest,
    db: DatabaseManager = Depends(get_db),
    validator: AlertRuleValidator = Depends(get_rule_validator)
):
    """Update an existing alert rule"""
    # Validate rule
    rule_data = request.dict()
    try:
        validator.validate_rule(rule_data)
    except AlertRuleValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    with db.get_session() as session:
        rule = session.query(AlertRuleV2).filter(AlertRuleV2.id == rule_id).first()

        if not rule:
            raise HTTPException(status_code=404, detail="Rule not found")

        # Update fields
        rule.name = request.name
        rule.description = request.description
        rule.scope = request.scope
        rule.kind = request.kind
        rule.enabled = request.enabled
        rule.host_selector_json = json.dumps(request.host_selector) if request.host_selector else None
        rule.container_selector_json = json.dumps(request.container_selector) if request.container_selector else None
        rule.labels_json = json.dumps(request.labels) if request.labels else None
        rule.metric = request.metric
        rule.operator = request.operator
        rule.threshold = request.threshold
        rule.occurrences = request.occurrences
        rule.clear_threshold = request.clear_threshold
        # Timing fields
        rule.alert_active_delay_seconds = request.alert_active_delay_seconds
        rule.alert_clear_delay_seconds = request.alert_clear_delay_seconds
        rule.notification_active_delay_seconds = request.notification_active_delay_seconds
        rule.notification_cooldown_seconds = request.notification_cooldown_seconds
        rule.severity = request.severity
        rule.grace_seconds = request.grace_seconds
        rule.depends_on_json = json.dumps(request.depends_on) if request.depends_on else None
        rule.notify_channels_json = json.dumps(request.notify_channels) if request.notify_channels else None
        rule.updated_at = datetime.now(timezone.utc)
        rule.version += 1

        session.commit()
        session.refresh(rule)

        return AlertRuleResponse(**{k: v for k, v in rule.__dict__.items() if not k.startswith('_')})


@router.delete("/rules/{rule_id}", dependencies=[Depends(get_rate_limit_dependency("rules_write")), Depends(require_scope("admin"))])
async def delete_rule(
    rule_id: str,
    db: DatabaseManager = Depends(get_db)
):
    """Delete an alert rule"""
    with db.get_session() as session:
        rule = session.query(AlertRuleV2).filter(AlertRuleV2.id == rule_id).first()

        if not rule:
            raise HTTPException(status_code=404, detail="Rule not found")

        session.delete(rule)
        session.commit()

        return {"status": "success", "message": "Rule deleted"}


# ==================== Statistics ====================

@router.get("/stats/", dependencies=[Depends(get_rate_limit_dependency("alerts"))])
async def get_alert_stats(
    db: DatabaseManager = Depends(get_db)
):
    """Get alert statistics"""
    with db.get_session() as session:
        total = session.query(AlertV2).count()
        open_count = session.query(AlertV2).filter(AlertV2.state == "open").count()
        snoozed_count = session.query(AlertV2).filter(AlertV2.state == "snoozed").count()
        resolved_count = session.query(AlertV2).filter(AlertV2.state == "resolved").count()

        # Count by severity (open only)
        critical = session.query(AlertV2).filter(
            AlertV2.state == "open",
            AlertV2.severity == "critical"
        ).count()
        error = session.query(AlertV2).filter(
            AlertV2.state == "open",
            AlertV2.severity == "error"
        ).count()
        warning = session.query(AlertV2).filter(
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
