class BackupError(Exception):
    """Base class for backup and restore failures."""


class BackupDecryptError(BackupError):
    """Wrong passphrase, or the archive was truncated or tampered with."""


class BackupFormatError(BackupDecryptError):
    """The file is not a DockMon backup, or uses unsupported parameters."""


class BackupValidationError(BackupError):
    """The decrypted archive or its database failed validation."""


class RestoreStateError(BackupError):
    """A restore could not be rolled back; the journal is kept for the next boot."""
