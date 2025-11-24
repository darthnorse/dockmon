package protocol

import (
	"encoding/json"
	"time"

	"github.com/darthnorse/dockmon-agent/pkg/types"
)

// EncodeMessage encodes a message to JSON bytes
func EncodeMessage(msg *types.Message) ([]byte, error) {
	msg.Timestamp = time.Now().UTC()
	return json.Marshal(msg)
}

// DecodeMessage decodes JSON bytes to a message
func DecodeMessage(data []byte) (*types.Message, error) {
	var msg types.Message
	if err := json.Unmarshal(data, &msg); err != nil {
		return nil, err
	}
	return &msg, nil
}

// NewCommandResponse creates a response message for a command
func NewCommandResponse(commandID string, payload interface{}, err error) *types.Message {
	msg := &types.Message{
		Type: "response",
		ID:   commandID,
		Payload: payload,
	}

	if err != nil {
		msg.Error = err.Error()
	}

	return msg
}

// NewEvent creates an event message
func NewEvent(eventType string, payload interface{}) *types.Message {
	return &types.Message{
		Type:    "event",
		Command: eventType,
		Payload: payload,
	}
}

// ParseCommand parses the payload of a command message into the target type
func ParseCommand(msg *types.Message, target interface{}) error {
	// Re-marshal and unmarshal to convert map to struct
	data, err := json.Marshal(msg.Payload)
	if err != nil {
		return err
	}

	return json.Unmarshal(data, target)
}
