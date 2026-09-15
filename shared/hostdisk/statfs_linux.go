package hostdisk

import "syscall"

func statfs(path string) (Statfs, error) {
	var st syscall.Statfs_t
	if err := syscall.Statfs(path, &st); err != nil {
		return Statfs{}, err
	}
	return Statfs{
		Blocks: uint64(st.Blocks),
		Bfree:  uint64(st.Bfree),
		Bavail: uint64(st.Bavail),
		Bsize:  nonNegative(int64(st.Bsize)),
		Frsize: nonNegative(int64(st.Frsize)),
	}, nil
}

func nonNegative(v int64) uint64 {
	if v < 0 {
		return 0
	}
	return uint64(v)
}
