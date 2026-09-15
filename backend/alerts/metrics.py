"""What an alert rule may declare, per scope.

Distinct from `capabilities`, which reports what a given host is *observed* to
send. This module is the schema side: which (scope, metric) pairs exist at all,
what thresholds mean for them, and which operators the engine can act on.

Both the evaluator's metric lookups and the API's rule validation derive from
here, so a metric cannot be readable by one and unknown to the other - that
mismatch is what let four container metrics be accepted and never evaluated.
"""
import math
from typing import Any, Dict, FrozenSet, Optional, Tuple

# Metrics with a live producer, by rule scope. No group-scope evaluator exists.
# disk_percent is used-percentage of the filesystem holding Docker's data-root
# (host root when that is unavailable), as df reports it.
PRODUCED_METRICS_BY_SCOPE: Dict[str, FrozenSet[str]] = {
    "host": frozenset({"cpu_percent", "memory_percent", "disk_percent"}),
    "container": frozenset({"cpu_percent", "memory_percent", "memory_usage", "memory_limit"}),
    "group": frozenset(),
}

# Accepted on rules but served by nothing yet. Empty today; kept so a metric
# the UI ships ahead of its producer has somewhere to live.
PENDING_METRICS_BY_SCOPE: Dict[str, FrozenSet[str]] = {
    "host": frozenset(),
    "container": frozenset(),
    "group": frozenset(),
}

VALID_SCOPES: FrozenSet[str] = frozenset(PRODUCED_METRICS_BY_SCOPE)

# Scopes a stored rule may carry. "system" belongs to the self-diagnostic rule,
# which is never metric-driven - it is absent from the maps above, so any metric
# named against it is still rejected.
STORABLE_SCOPES: FrozenSet[str] = VALID_SCOPES | frozenset({"system"})

# Fields whose change can invalidate a metric rule as a whole, so an update
# touching any of them has to be validated against the merged record.
METRIC_RULE_FIELDS: FrozenSet[str] = frozenset(
    {"scope", "metric", "threshold", "clear_threshold", "operator"}
)


# (min, max) per (scope, metric); None means unbounded above.
METRIC_RANGES: Dict[Tuple[str, str], Tuple[float, Optional[float]]] = {
    ("host", "cpu_percent"): (0, 100),
    ("container", "cpu_percent"): (0, 6400),  # a container spans many cores
    ("host", "memory_percent"): (0, 100),
    ("container", "memory_percent"): (0, 100),
    ("host", "disk_percent"): (0, 100),
    ("container", "memory_usage"): (0, None),  # bytes
    ("container", "memory_limit"): (0, None),
}

# Operators AlertEngine._check_breach can actually act on. `!=` is absent: it
# has no branch there and falls through to returning False, so such a rule
# never fires.
BREACH_OPERATORS: FrozenSet[str] = frozenset({">=", "<=", ">", "<", "=="})

# Operators whose clear threshold must sit at or below the alert threshold.
_RISING_OPERATORS: FrozenSet[str] = frozenset({">=", ">"})
_FALLING_OPERATORS: FrozenSet[str] = frozenset({"<=", "<"})


def metrics_for_scope(scope: str) -> FrozenSet[str]:
    """Every metric a rule may name in this scope, produced or pending."""
    return PRODUCED_METRICS_BY_SCOPE.get(scope, frozenset()) | PENDING_METRICS_BY_SCOPE.get(
        scope, frozenset()
    )


def is_produced(scope: Optional[str], metric: Optional[str]) -> bool:
    """Whether some producer actually serves this pair today."""
    if not scope or not metric:
        return False
    return metric in PRODUCED_METRICS_BY_SCOPE.get(scope, frozenset())


def _check_number(label: str, value: Any, bounds: Tuple[float, Optional[float]]) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{label} must be a number")
    # json.loads accepts Infinity and NaN, which slip past a range check.
    if not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")

    low, high = bounds
    if value < low:
        raise ValueError(f"{label} must be at least {low}")
    if high is not None and value > high:
        raise ValueError(f"{label} must be between {low} and {high}")



def validate_metric_fields(
    scope: Optional[str],
    metric: Optional[str],
    threshold: Optional[float],
    clear_threshold: Optional[float],
    operator: Optional[str],
) -> None:
    """Validate the metric half of a rule, raising ValueError with the reason.

    Framework-agnostic on purpose: the create model surfaces the error as a 422
    and the update route as a 400. Callers pass the *merged* record, never a
    partial payload, or a partial edit could store a combination that is only
    invalid as a whole.
    """
    # Before the metric shortcut: scope is NOT NULL in the database, and an
    # explicit null on update would otherwise reach it as an IntegrityError.
    if scope not in STORABLE_SCOPES:
        raise ValueError(
            f"Invalid scope {scope!r}. Must be one of: {', '.join(sorted(VALID_SCOPES))}"
        )

    if metric is None:
        return  # Event-driven rule; the engine selects on metric IS NULL.

    allowed = metrics_for_scope(scope)
    if metric not in allowed:
        detail = ", ".join(sorted(allowed)) if allowed else "none"
        raise ValueError(
            f"Metric {metric!r} is not available for {scope} rules and would never "
            f"be evaluated. Available: {detail}"
        )

    if threshold is None:
        raise ValueError(f"threshold is required for {metric!r} rules")
    if operator is None:
        raise ValueError(f"operator is required for {metric!r} rules")
    if operator not in BREACH_OPERATORS:
        raise ValueError(
            f"Operator {operator!r} is not evaluated and the rule would never fire. "
            f"Must be one of: {', '.join(sorted(BREACH_OPERATORS))}"
        )

    bounds = METRIC_RANGES[(scope, metric)]
    _check_number(f"threshold for {metric!r} ({scope} scope)", threshold, bounds)

    if clear_threshold is None:
        return

    _check_number(f"clear_threshold for {metric!r} ({scope} scope)", clear_threshold, bounds)

    # Clearing re-tests the value against clear_threshold with the same
    # operator and clears when it does not breach. A clear threshold on the
    # wrong side of the alert threshold therefore clears while still breaching,
    # and the alert re-fires on the next cycle.
    if operator == "==" and clear_threshold != threshold:
        # Equality has no "less strict" side: any other clear threshold leaves
        # the alert unable to clear at the value that raised it.
        raise ValueError(
            f"clear_threshold must equal the threshold ({threshold}) for '==' rules"
        )
    if operator in _RISING_OPERATORS and clear_threshold > threshold:
        raise ValueError(
            f"clear_threshold must be at most the threshold ({threshold}) for "
            f"{operator!r} rules, otherwise the alert clears while still breaching"
        )
    if operator in _FALLING_OPERATORS and clear_threshold < threshold:
        raise ValueError(
            f"clear_threshold must be at least the threshold ({threshold}) for "
            f"{operator!r} rules, otherwise the alert clears while still breaching"
        )
