#!/usr/bin/env python3
"""
DockMon Backup Tool

Back up and restore DockMon's own state: the database, the encryption key and
the compose/env files of every stack. Container volumes are not included.
Run via docker exec (the script lives at /app/backend):

    docker exec -it dockmon python backend/manage_backup.py create /app/data/dockmon.dmbak
    docker exec -it dockmon python backend/manage_backup.py verify /app/data/dockmon.dmbak
    docker exec -it dockmon python backend/manage_backup.py stage /app/data/dockmon.dmbak
    docker restart dockmon        # the staged restore is applied on start

Backups are always encrypted. The passphrase is prompted for, or read from
--passphrase-file for scripted use. It cannot be recovered: without it the
backup is unreadable.

apply-staged runs automatically from the container's startup script, before
database migrations. A restore interrupted by a crash is finished or rolled
back on the next start.
"""

import argparse
import getpass
import os
import sys
from pathlib import Path
from typing import List, Optional

from backup.archive import create_backup
from backup.crypto import DEFAULT_KDF, MIN_PASSPHRASE_LENGTH
from backup.errors import BackupError, RestoreStateError
from backup.fsutil import fsync_dir
from backup.oplock import operation_lock
from backup.paths import BackupPaths
from backup.restore import (
    ApplyOutcome,
    apply_staged,
    cancel_staged,
    delete_rollback,
    list_rollbacks,
    pending_manifest,
    stage_archive,
    stage_rollback,
    verify_archive,
)
from migrate import run_migrations

BACKUP_KDF = DEFAULT_KDF
CLI_INITIATOR = {"username": "manage_backup CLI"}
RESTART_HINT = "Restart the DockMon container to apply it: docker restart dockmon"


class CliError(Exception):
    """A user-facing failure; printed without a traceback."""


def _read_passphrase(args, confirm: bool) -> str:
    if args.passphrase_file:
        passphrase = Path(args.passphrase_file).read_text().rstrip("\r\n")
    elif sys.stdin.isatty():
        passphrase = getpass.getpass("Backup passphrase: ")
        if confirm and getpass.getpass("Repeat passphrase: ") != passphrase:
            raise CliError("Passphrases do not match")
    else:
        raise CliError("No terminal to prompt for a passphrase; use --passphrase-file")
    if confirm and len(passphrase) < MIN_PASSPHRASE_LENGTH:
        raise CliError(f"Passphrase must be at least {MIN_PASSPHRASE_LENGTH} characters")
    return passphrase


def _describe(manifest: dict) -> str:
    summary = manifest["summary"]
    stats = "with" if manifest.get("stats_history_included") else "without"
    return (
        f"DockMon {manifest.get('app_version')} backup from {manifest['created_at']} "
        f"(schema {manifest['alembic_revision']}): {summary['hosts']} hosts, "
        f"{summary['users']} users, {summary['alert_rules']} alert rules, "
        f"{len(summary['stacks'])} stacks, {stats} stats history"
    )


def migrate_candidate(db_path: Path) -> bool:
    previous = os.environ.get("DATABASE_PATH")
    os.environ["DATABASE_PATH"] = str(db_path)
    try:
        return run_migrations()
    finally:
        if previous is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = previous


def cmd_create(paths: BackupPaths, args) -> None:
    out = Path(args.output)
    if os.path.lexists(out):
        raise CliError(f"{out} already exists; refusing to overwrite it")
    passphrase = _read_passphrase(args, confirm=True)
    partial = out.with_name(out.name + ".partial")
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            manifest = create_backup(paths, f, passphrase, include_stats=not args.no_stats, kdf=BACKUP_KDF)
            f.flush()
            os.fsync(f.fileno())
        os.rename(partial, out)
        fsync_dir(out.parent)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    print(f"Wrote {out}")
    print(_describe(manifest))
    print("Keep the passphrase somewhere safe: the backup cannot be restored without it.")


def cmd_verify(paths: BackupPaths, args) -> None:
    manifest = verify_archive(paths, Path(args.archive), _read_passphrase(args, confirm=False))
    print(f"OK: {_describe(manifest)}")


def cmd_stage(paths: BackupPaths, args) -> None:
    manifest = stage_archive(
        paths, Path(args.archive), _read_passphrase(args, confirm=False), replace=args.replace, initiator=CLI_INITIATOR
    )
    print(f"Staged: {_describe(manifest)}")
    print(RESTART_HINT)


def cmd_status(paths: BackupPaths, _args) -> None:
    manifest = pending_manifest(paths)
    print(f"Staged restore: {_describe(manifest) if manifest else 'none'}")
    rollbacks = list_rollbacks(paths)
    print(f"Rollback copies: {len(rollbacks)}")


def cmd_cancel(paths: BackupPaths, _args) -> None:
    print("Staged restore cancelled." if cancel_staged(paths) else "No staged restore.")


def cmd_apply_staged(paths: BackupPaths, _args) -> None:
    outcome = apply_staged(paths, migrate_candidate)
    if outcome is ApplyOutcome.APPLIED:
        print("Restore applied. All sessions were signed out.")
    elif outcome is ApplyOutcome.FAILED:
        print(
            "RESTORE FAILED and was rolled back; DockMon is starting on its previous data. "
            "See the log above for the reason.",
            file=sys.stderr,
        )


def cmd_list_rollbacks(paths: BackupPaths, _args) -> None:
    rollbacks = list_rollbacks(paths)
    if not rollbacks:
        print("No rollback copies.")
        return
    print("Rollback copies (the state a restore replaced; they contain plaintext secrets):")
    for rollback in rollbacks:
        print(f"  {rollback['id']}  taken {rollback['created_at']}")


def cmd_rollback(paths: BackupPaths, args) -> None:
    manifest = stage_rollback(paths, args.rollback_id, replace=args.replace, initiator=CLI_INITIATOR)
    print(f"Staged rollback: {_describe(manifest)}")
    print(RESTART_HINT)


def cmd_delete_rollback(paths: BackupPaths, args) -> None:
    delete_rollback(paths, args.rollback_id)
    print(f"Deleted rollback copy {args.rollback_id}.")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DockMon Backup Tool")
    sub = parser.add_subparsers(dest="command", required=True)

    def with_passphrase(p):
        p.add_argument("--passphrase-file", help="Read the passphrase from this file instead of prompting")
        return p

    create = with_passphrase(sub.add_parser("create", help="Write an encrypted backup"))
    create.add_argument("output")
    create.add_argument("--no-stats", action="store_true", help="Leave out stats history (smaller backup)")

    verify = with_passphrase(sub.add_parser("verify", help="Check a backup without staging it"))
    verify.add_argument("archive")

    stage = with_passphrase(sub.add_parser("stage", help="Stage a backup; it is applied on the next start"))
    stage.add_argument("archive")
    stage.add_argument("--replace", action="store_true", help="Replace an already staged restore")

    sub.add_parser("status", help="Show the staged restore and rollback copies")
    sub.add_parser("cancel", help="Cancel the staged restore")
    sub.add_parser("apply-staged", help="Apply a staged restore (run by the startup script)")
    sub.add_parser("list-rollbacks", help="List rollback copies")

    rollback = sub.add_parser("rollback", help="Stage a rollback copy for restore")
    rollback.add_argument("rollback_id")
    rollback.add_argument("--replace", action="store_true", help="Replace an already staged restore")

    delete = sub.add_parser("delete-rollback", help="Delete a rollback copy")
    delete.add_argument("rollback_id")
    return parser


READ_ONLY_COMMANDS = {"status", "list-rollbacks"}

COMMANDS = {
    "create": cmd_create,
    "verify": cmd_verify,
    "stage": cmd_stage,
    "status": cmd_status,
    "cancel": cmd_cancel,
    "apply-staged": cmd_apply_staged,
    "list-rollbacks": cmd_list_rollbacks,
    "rollback": cmd_rollback,
    "delete-rollback": cmd_delete_rollback,
}


def main(argv: Optional[List[str]] = None, paths: Optional[BackupPaths] = None) -> int:
    args = _parser().parse_args(argv)
    paths = paths or BackupPaths.from_environment()
    try:
        if args.command in READ_ONLY_COMMANDS:
            COMMANDS[args.command](paths, args)
        else:
            with operation_lock(paths):
                COMMANDS[args.command](paths, args)
    except RestoreStateError as e:
        print(f"RESTORE STATE ERROR: {e}", file=sys.stderr)
        return 1
    except (BackupError, CliError, ValueError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nOperation cancelled.")
        sys.exit(1)
