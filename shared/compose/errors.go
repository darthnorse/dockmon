package compose

import (
	"fmt"
	"strings"
)

// ErrorCategory categorizes compose errors for proper handling
type ErrorCategory string

const (
	ErrorCategoryValidation ErrorCategory = "validation" // Invalid compose file
	ErrorCategoryNetwork    ErrorCategory = "network"    // Registry unreachable, DNS failure
	ErrorCategoryImage      ErrorCategory = "image"      // Pull failed, not found, auth required
	ErrorCategoryResource   ErrorCategory = "resource"   // Port conflict, volume in use
	ErrorCategoryHealth     ErrorCategory = "health"     // Health check failed/timeout
	ErrorCategoryDocker     ErrorCategory = "docker"     // Docker daemon error
	ErrorCategoryInternal   ErrorCategory = "internal"   // Unexpected Go service error
)

// ComposeError represents a structured error from compose operations
type ComposeError struct {
	Category  ErrorCategory `json:"category"`
	Message   string        `json:"message"`
	Service   string        `json:"service,omitempty"`  // Which service failed
	Details   string        `json:"details,omitempty"`  // Stack trace or additional info
	Retryable bool          `json:"retryable"`          // Can user retry?
}

// Error implements the error interface
func (e *ComposeError) Error() string {
	if e.Service != "" {
		return fmt.Sprintf("Service '%s': %s", e.Service, e.Message)
	}
	return e.Message
}

// NewValidationError creates a validation error
func NewValidationError(message string) *ComposeError {
	return &ComposeError{
		Category:  ErrorCategoryValidation,
		Message:   message,
		Retryable: false,
	}
}

// NewNetworkError creates a network error
func NewNetworkError(message string) *ComposeError {
	return &ComposeError{
		Category:  ErrorCategoryNetwork,
		Message:   message,
		Retryable: true,
	}
}

// NewImageError creates an image pull error
func NewImageError(message, service string) *ComposeError {
	return &ComposeError{
		Category:  ErrorCategoryImage,
		Message:   message,
		Service:   service,
		Retryable: true,
	}
}

// NewResourceError creates a resource conflict error
func NewResourceError(message string) *ComposeError {
	return &ComposeError{
		Category:  ErrorCategoryResource,
		Message:   message,
		Retryable: false,
	}
}

// NewHealthError creates a health check error
func NewHealthError(message, service string) *ComposeError {
	return &ComposeError{
		Category:  ErrorCategoryHealth,
		Message:   message,
		Service:   service,
		Retryable: true,
	}
}

// NewDockerError creates a Docker daemon error
func NewDockerError(message string) *ComposeError {
	return &ComposeError{
		Category:  ErrorCategoryDocker,
		Message:   message,
		Retryable: true,
	}
}

// NewInternalError creates an internal error
func NewInternalError(message string) *ComposeError {
	return &ComposeError{
		Category:  ErrorCategoryInternal,
		Message:   message,
		Retryable: false,
	}
}

// CategorizeError attempts to categorize an error based on its message
func CategorizeError(err error) *ComposeError {
	if err == nil {
		return nil
	}

	msg := err.Error()
	msgLower := strings.ToLower(msg)

	// Check for specific error patterns
	switch {
	case strings.Contains(msgLower, "yaml") || strings.Contains(msgLower, "parse") ||
		strings.Contains(msgLower, "invalid"):
		return NewValidationError(msg)

	case strings.Contains(msgLower, "pull") || strings.Contains(msgLower, "not found") ||
		strings.Contains(msgLower, "manifest unknown"):
		return &ComposeError{
			Category:  ErrorCategoryImage,
			Message:   msg,
			Retryable: true,
		}

	case strings.Contains(msgLower, "port") && strings.Contains(msgLower, "already"):
		return NewResourceError(msg)

	case strings.Contains(msgLower, "network") || strings.Contains(msgLower, "dns") ||
		strings.Contains(msgLower, "connect"):
		return NewNetworkError(msg)

	case strings.Contains(msgLower, "health") || strings.Contains(msgLower, "unhealthy"):
		return &ComposeError{
			Category:  ErrorCategoryHealth,
			Message:   msg,
			Retryable: true,
		}

	case strings.Contains(msgLower, "docker") || strings.Contains(msgLower, "daemon"):
		return NewDockerError(msg)

	default:
		return NewInternalError(msg)
	}
}

// CategorizeErrorString returns the category string for an error message
// Used for logging and metrics
func CategorizeErrorString(errMsg string) string {
	if errMsg == "" {
		return ""
	}
	errLower := strings.ToLower(errMsg)
	switch {
	case strings.Contains(errLower, "pull"):
		return "image_pull"
	case strings.Contains(errLower, "health"):
		return "health_check"
	case strings.Contains(errLower, "network"):
		return "network"
	case strings.Contains(errLower, "port") && strings.Contains(errLower, "already"):
		return "port_conflict"
	case strings.Contains(errLower, "timeout"):
		return "timeout"
	default:
		return "other"
	}
}
