//go:build !linux

package hostdisk

import "errors"

func statfs(string) (Statfs, error) {
	return Statfs{}, errors.ErrUnsupported
}
