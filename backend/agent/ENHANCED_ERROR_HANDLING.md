# Enhanced Error Handling for Agent Command Executor

## Overview
Rock-solid error handling for agent command execution with detailed error codes, smart retry logic, and circuit breaker pattern to prevent cascade failures.

## Current State Analysis

### Existing Error Handling
```python
class CommandStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"     # Too generic - no distinction between error types
    TIMEOUT = "timeout"

class CommandResult:
    status: CommandStatus
    success: bool
    response: Optional[Dict[str, Any]]
    error: Optional[str]  # Human-readable string only
    duration_seconds: float
```

### Problems
1. **Generic error status**: Can't distinguish network errors from permission errors
2. **No retry logic**: Single attempt, even for transient failures
3. **No circuit breaker**: Continues sending commands to failing agents
4. **Poor error context**: No tracking of retry attempts or error classification

## Enhanced Error Handling Architecture

### 1. Detailed Error Codes

```python
class CommandErrorCode(Enum):
    """Detailed error codes for command execution failures"""

    # Network/Connection errors (RETRYABLE)
    NETWORK_ERROR = "network_error"              # Connection issues, send failures
    AGENT_DISCONNECTED = "agent_disconnected"    # Agent went offline during execution
    AGENT_NOT_CONNECTED = "agent_not_connected"  # Agent not connected when command sent

    # Timeout errors (SOMETIMES RETRYABLE - depends on operation)
    TIMEOUT = "timeout"                          # Command timeout

    # Docker/Permission errors (NON-RETRYABLE)
    PERMISSION_DENIED = "permission_denied"      # Docker permission issues
    DOCKER_ERROR = "docker_error"                # Docker daemon errors

    # Agent errors (NON-RETRYABLE)
    AGENT_ERROR = "agent_error"                  # Agent-side execution error
    INVALID_RESPONSE = "invalid_response"        # Malformed response from agent

    # Circuit breaker (NON-RETRYABLE)
    CIRCUIT_OPEN = "circuit_open"                # Circuit breaker is open

    # Unknown (RETRYABLE with caution)
    UNKNOWN_ERROR = "unknown_error"              # Catch-all
```

**Classification**:
- **Retryable**: NETWORK_ERROR, AGENT_DISCONNECTED, TIMEOUT (some cases)
- **Non-retryable**: PERMISSION_DENIED, DOCKER_ERROR, AGENT_ERROR, INVALID_RESPONSE, CIRCUIT_OPEN

### 2. Enhanced CommandResult

```python
@dataclass
class CommandResult:
    """Result of command execution with enhanced error context"""
    status: CommandStatus
    success: bool
    response: Optional[Dict[str, Any]]
    error: Optional[str]                    # Human-readable error message
    error_code: Optional[CommandErrorCode]  # NEW: Machine-readable error code
    duration_seconds: float = 0.0
    attempt: int = 1                        # NEW: Which attempt succeeded/failed (1-based)
    total_attempts: int = 1                 # NEW: Total attempts made
    retried: bool = False                   # NEW: Whether command was retried
```

### 3. Retry Logic with Exponential Backoff

```python
@dataclass
class RetryPolicy:
    """Policy for retrying failed commands"""
    max_attempts: int = 3                   # Maximum retry attempts
    initial_delay: float = 1.0              # Initial delay in seconds
    max_delay: float = 30.0                 # Maximum delay in seconds
    backoff_multiplier: float = 2.0         # Exponential backoff multiplier
    jitter: bool = True                     # Add randomization to prevent thundering herd

    # Which error codes should trigger retry
    retryable_error_codes: List[CommandErrorCode] = field(default_factory=lambda: [
        CommandErrorCode.NETWORK_ERROR,
        CommandErrorCode.AGENT_DISCONNECTED,
        CommandErrorCode.TIMEOUT,  # Only retry timeout for idempotent operations
        CommandErrorCode.UNKNOWN_ERROR
    ])
```

**Exponential Backoff Algorithm**:
```python
delay = min(initial_delay * (backoff_multiplier ** (attempt - 1)), max_delay)
if jitter:
    delay *= (0.5 + random.random())  # Add 0-50% jitter
```

**Example delays** (with jitter disabled):
- Attempt 1: immediate
- Attempt 2: 1.0s delay
- Attempt 3: 2.0s delay
- Attempt 4: 4.0s delay (if max_attempts > 3)

**Retry Decision Flow**:
```
Command fails with error_code
  ↓
Is error_code in retryable_error_codes?
  ↓ YES                    ↓ NO
Have attempts < max_attempts?   Return error immediately
  ↓ YES        ↓ NO
Wait delay     Return error
  ↓
Retry command
```

### 4. Circuit Breaker Pattern

Prevents cascade failures by failing fast when an agent is consistently failing.

```python
class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"        # Normal operation
    OPEN = "open"           # Failing - reject all commands
    HALF_OPEN = "half_open" # Testing recovery - allow probe commands

class CircuitBreaker:
    """
    Circuit breaker for agent command execution.

    State Machine:
    CLOSED → OPEN: After failure_threshold failures in window
    OPEN → HALF_OPEN: After timeout_seconds
    HALF_OPEN → CLOSED: After success_threshold successes
    HALF_OPEN → OPEN: After any failure
    """

    # Thresholds
    failure_threshold: int = 5          # Failures to trigger OPEN
    success_threshold: int = 2          # Successes to trigger CLOSED
    failure_window_seconds: int = 60    # Time window for failure tracking
    timeout_seconds: int = 30           # Time in OPEN before HALF_OPEN

    # State tracking (per agent)
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: Optional[datetime] = None
    opened_at: Optional[datetime] = None
```

**State Transitions**:

**CLOSED → OPEN**:
- Condition: `failure_count >= failure_threshold` within `failure_window_seconds`
- Action: Set `state = OPEN`, record `opened_at`
- Effect: All commands fail immediately with `CIRCUIT_OPEN` error

**OPEN → HALF_OPEN**:
- Condition: `(now - opened_at) >= timeout_seconds`
- Action: Set `state = HALF_OPEN`, reset `success_count = 0`
- Effect: Allow single probe command through

**HALF_OPEN → CLOSED**:
- Condition: `success_count >= success_threshold`
- Action: Set `state = CLOSED`, reset `failure_count = 0`
- Effect: Resume normal operation

**HALF_OPEN → OPEN**:
- Condition: Any failure
- Action: Set `state = OPEN`, record `opened_at`
- Effect: Back to failing fast

**Per-Agent Tracking**:
- Each agent has its own CircuitBreaker instance
- Stored in `AgentCommandExecutor._circuit_breakers: Dict[str, CircuitBreaker]`
- Prevents one failing agent from affecting others

### 5. Integration with AgentCommandExecutor

**Enhanced execute_command() flow**:

```python
async def execute_command(
    agent_id: str,
    command: dict,
    timeout: float = 30.0,
    retry_policy: Optional[RetryPolicy] = None
) -> CommandResult:
    """
    Execute command with retry logic and circuit breaker.

    Flow:
    1. Check circuit breaker state
       - If OPEN → fail immediately with CIRCUIT_OPEN
       - If HALF_OPEN → allow single probe attempt
    2. Attempt command execution
    3. If failure and retryable:
       - Apply exponential backoff
       - Retry up to max_attempts
    4. Update circuit breaker based on result
    5. Return CommandResult with error_code and retry context
    """
```

**Detailed Flow**:

```
START
  ↓
Check circuit breaker
  ↓
OPEN? → Return CommandResult(error_code=CIRCUIT_OPEN)
  ↓ NO
HALF_OPEN? → Set probe flag
  ↓
attempt = 1
  ↓
┌─────────────────────┐
│ Execute command     │
│ - Check connected   │
│ - Send command      │
│ - Wait for response │
└─────────────────────┘
  ↓
Success? → Update circuit breaker → Return SUCCESS
  ↓ NO
Classify error → error_code
  ↓
Is retryable AND attempt < max_attempts?
  ↓ YES                        ↓ NO
Calculate backoff delay        Update circuit breaker
  ↓                           ↓
Wait delay                     Return ERROR with error_code
  ↓
attempt++
  ↓
Go to "Execute command" ───────┘
```

## Implementation Plan (TDD)

### Phase 1: Enhanced Error Codes
**RED**:
- Write test for each error code scenario
- Test error classification (retryable vs non-retryable)
- All tests fail (error_code field doesn't exist)

**GREEN**:
- Add CommandErrorCode enum
- Add error_code field to CommandResult
- Update execute_command() to classify errors and set error_code
- All tests pass

**REFACTOR**:
- Extract error classification logic into helper method
- Add comprehensive docstrings
- Ensure code clarity

### Phase 2: Retry Logic
**RED**:
- Test retry with exponential backoff
- Test retry only for retryable errors
- Test max_attempts enforcement
- Test jitter application
- All tests fail (retry logic doesn't exist)

**GREEN**:
- Implement RetryPolicy class
- Add retry_policy parameter to execute_command()
- Implement retry loop with backoff
- All tests pass

**REFACTOR**:
- Extract backoff calculation into helper
- Optimize retry loop
- Add logging for retry attempts

### Phase 3: Circuit Breaker
**RED**:
- Test state transitions (CLOSED → OPEN → HALF_OPEN → CLOSED)
- Test failure threshold triggers OPEN
- Test timeout triggers HALF_OPEN
- Test commands rejected in OPEN state
- All tests fail (circuit breaker doesn't exist)

**GREEN**:
- Implement CircuitBreaker class
- Add circuit breaker tracking in AgentCommandExecutor
- Integrate circuit check into execute_command()
- All tests pass

**REFACTOR**:
- Optimize circuit breaker state management
- Add circuit breaker metrics/monitoring hooks
- Clean up state transition logic

## Testing Strategy

### Unit Tests
- `test_error_codes.py`: Test error code classification
- `test_retry_logic.py`: Test retry with various policies
- `test_circuit_breaker.py`: Test circuit breaker state machine
- `test_integration.py`: End-to-end command execution with all features

### Test Coverage Goals
- Error code classification: 100%
- Retry logic: 100%
- Circuit breaker state transitions: 100%
- Integration: All critical paths covered

## Backwards Compatibility

- `CommandResult.error_code` is optional (defaults to None)
- `retry_policy` parameter is optional (defaults to no retry)
- Circuit breaker is enabled by default but can be disabled
- Existing code continues to work without changes

## Monitoring and Observability

### Metrics to Track
- Command success/failure rates (by error_code)
- Retry attempts per command
- Circuit breaker state changes
- Average command duration (with/without retries)

### Logging
- Log each retry attempt with backoff delay
- Log circuit breaker state transitions
- Log error_code for all failures
- Include correlation_id in all logs

## Security Considerations

- **Rate limiting**: Circuit breaker prevents DoS by failing fast
- **Resource exhaustion**: Max retry attempts prevent infinite loops
- **Information disclosure**: Error messages sanitized (no sensitive data)
- **Audit trail**: All command attempts logged with timestamps

## Performance Impact

- **Minimal overhead**: Circuit breaker check is O(1)
- **Retry delays**: Configurable, defaults to reasonable values
- **Memory**: Per-agent circuit breaker state (negligible)
- **Async-friendly**: All retry delays use asyncio.sleep() (non-blocking)

## Configuration

Default configuration for production:

```python
DEFAULT_RETRY_POLICY = RetryPolicy(
    max_attempts=3,
    initial_delay=1.0,
    max_delay=30.0,
    backoff_multiplier=2.0,
    jitter=True,
    retryable_error_codes=[
        CommandErrorCode.NETWORK_ERROR,
        CommandErrorCode.AGENT_DISCONNECTED,
        CommandErrorCode.TIMEOUT
    ]
)

CIRCUIT_BREAKER_CONFIG = {
    "failure_threshold": 5,
    "success_threshold": 2,
    "failure_window_seconds": 60,
    "timeout_seconds": 30
}
```

## Future Enhancements

- **Adaptive retry**: Adjust retry policy based on historical success rates
- **Bulkhead pattern**: Limit concurrent commands per agent
- **Metrics export**: Prometheus metrics for monitoring
- **Health checks**: Periodic agent health probes
- **Graceful degradation**: Fallback mechanisms for critical operations
