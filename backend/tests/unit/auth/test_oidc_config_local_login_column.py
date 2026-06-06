"""
Schema test for oidc_config.local_login_disabled.

The column backs the SSO-only enforcement switch. It must exist, be NOT NULL,
and default to False so existing deployments keep local login on until an
operator explicitly disables it.
"""

from datetime import datetime, timezone

from database import OIDCConfig


def test_local_login_disabled_defaults_to_false(db_session):
    """A freshly created OIDCConfig has local login enabled (flag False)."""
    config = OIDCConfig(
        id=1,
        enabled=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(config)
    db_session.commit()
    db_session.refresh(config)

    assert config.local_login_disabled is False


def test_local_login_disabled_persists_when_set(db_session):
    """The flag round-trips through the database as True."""
    config = OIDCConfig(
        id=1,
        enabled=True,
        local_login_disabled=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(config)
    db_session.commit()

    stored = db_session.query(OIDCConfig).filter(OIDCConfig.id == 1).first()
    assert stored.local_login_disabled is True
