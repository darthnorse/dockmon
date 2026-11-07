"""Migration 048 removes update state left by the registry-identity bugs."""
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base, ContainerUpdate, DockerHostDB, ImageDigestCache

BACKEND_DIR = Path(__file__).resolve().parents[2]
HOST_ID = "7be442c9-24bc-4047-b33a-41bbf51ea2f9"
DIGEST = "sha256:" + "a" * 64


def row(container, current_image, latest_image, mode="latest", **overrides):
    values = dict(
        container_id=f"{HOST_ID}:{container}",
        host_id=HOST_ID,
        current_image=current_image,
        current_digest=DIGEST,
        latest_image=latest_image,
        latest_digest=DIGEST,
        latest_version="2.0.0",
        update_available=True,
        auto_update_enabled=True,
        floating_tag_mode=mode,
    )
    values.update(overrides)
    return ContainerUpdate(**values)


@pytest.fixture
def migrated_session():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    url = f"sqlite:///{path}"
    engine = create_engine(url)
    try:
        Base.metadata.create_all(bind=engine)
        with sessionmaker(bind=engine)() as session:
            session.add(DockerHostDB(id=HOST_ID, name="docker-1", url="unix:///var/run/docker.sock", is_active=True))
            session.add_all([
                row("aaaaaaaaaaaa", "registry:5000/app", "registry:latest"),
                row("bbbbbbbbbbbb", "registry:5000/org/app", "registry:latest"),
                row("222222222222", "registry:5000/app", "registry:latest", mode="exact"),
                row("cccccccccccc", "registry:5000/app:1.2.3", "registry:5000/app:latest"),
                row("dddddddddddd", "registry:5000/app", "registry:5000/app:latest"),
                row("eeeeeeeeeeee", "nginx:1.25", "nginx:latest"),
                row("ffffffffffff", "registry:5000/app", "registry:5000/app", mode="exact"),
                row("111111111111", f"registry:5000/app@{DIGEST}", "registry:5000/app@sha256:latest"),
            ])
            session.add(ImageDigestCache(
                cache_key="notdocker.io/org/app:1:linux/amd64",
                latest_digest=DIGEST,
                checked_at=datetime.now(timezone.utc),
            ))
            session.commit()
        engine.dispose()

        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        cfg.set_main_option("sqlalchemy.url", url)
        command.stamp(cfg, "047_backup_schedule")
        command.upgrade(cfg, "048_registry_leak_cleanup")

        migrated = create_engine(url)
        with sessionmaker(bind=migrated)() as session:
            yield session
        migrated.dispose()
    finally:
        os.unlink(path)


def fetch(session, container):
    return session.query(ContainerUpdate).filter_by(container_id=f"{HOST_ID}:{container}").one()


@pytest.mark.parametrize("container", ["aaaaaaaaaaaa", "bbbbbbbbbbbb", "222222222222"])
def test_wrong_registry_target_is_cleared_and_settings_kept(migrated_session, container):
    cleared = fetch(migrated_session, container)

    assert cleared.update_available is False
    assert cleared.latest_image is None
    assert cleared.latest_digest is None
    assert cleared.latest_version is None
    assert cleared.auto_update_enabled is True
    assert cleared.floating_tag_mode in ("latest", "exact")


@pytest.mark.parametrize("container", [
    "cccccccccccc", "dddddddddddd", "eeeeeeeeeeee", "ffffffffffff", "111111111111",
])
def test_other_rows_are_untouched(migrated_session, container):
    untouched = fetch(migrated_session, container)

    assert untouched.update_available is True
    assert untouched.latest_image is not None
    assert untouched.latest_digest == DIGEST


def test_digest_cache_is_emptied(migrated_session):
    assert migrated_session.query(ImageDigestCache).count() == 0
