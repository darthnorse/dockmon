package main

// truncateID truncates an ID string to specified length
func truncateID(id string, length int) string {
	if len(id) <= length {
		return id
	}
	return id[:length]
}
