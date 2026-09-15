// Package mountinfo parses /proc/self/mountinfo lines per proc(5).
package mountinfo

import (
	"strconv"
	"strings"
)

// ParseLine extracts (root, mount_point) from one /proc/self/mountinfo
// line per proc(5). The format is:
//
//	mount_id parent_id major:minor root mount_point options [optional_fields]... - fs_type source super_options
//
// Optional fields are zero or more shared:N / master:N / propagate_from:N /
// unbindable tags; their list is terminated by a single "-" token followed
// by exactly three fields (fs_type, source, super_options). We validate the
// "-" token AND the trailing three fields so malformed lines fail closed
// rather than silently returning garbage.
func ParseLine(line string) (root, mountPoint string, ok bool) {
	fields := strings.Fields(line)
	if len(fields) < 10 {
		// Minimum: id parent maj:min root mountpoint opts - fstype source superopts
		return "", "", false
	}
	dashIdx := -1
	for i := 6; i < len(fields); i++ {
		if fields[i] == "-" {
			dashIdx = i
			break
		}
	}
	if dashIdx < 0 || len(fields)-dashIdx < 4 {
		// Need "-" plus at least three trailing fields.
		return "", "", false
	}
	root = Unescape(fields[3])
	mountPoint = Unescape(fields[4])
	return root, mountPoint, true
}

// Unescape decodes the kernel's mountinfo path encoding. Per fs/seq_file.c,
// the kernel escapes ' ', '\t', '\n', and '\\' as \040, \011, \012, \134.
// Other bytes pass through unchanged. We accept any \NNN octal triplet to be
// permissive against future kernel additions.
func Unescape(s string) string {
	var b strings.Builder
	b.Grow(len(s))
	for i := 0; i < len(s); i++ {
		// A backslash escape needs three octal digits after it. The triplet
		// occupies indices i+1..i+3, so we need i+4 <= len(s).
		if s[i] == '\\' && i+4 <= len(s) {
			if v, err := strconv.ParseUint(s[i+1:i+4], 8, 8); err == nil {
				b.WriteByte(byte(v))
				i += 3
				continue
			}
		}
		b.WriteByte(s[i])
	}
	return b.String()
}
