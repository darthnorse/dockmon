package docker

// TruncateID truncates a Docker ID to the specified length
func TruncateID(id string, length int) string {
	if len(id) <= length {
		return id
	}
	return id[:length]
}
