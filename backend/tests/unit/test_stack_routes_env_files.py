"""StackCreate/Update/Response carry an env_files map (#205)."""
from deployment.stack_routes import StackCreate, StackUpdate, StackResponse


def test_models_accept_env_files_map():
    c = StackCreate(name="myapp", compose_yaml="services: {}\n",
                    env_files={".env": "A=1", ".db.env": "P=2"})
    assert c.env_files == {".env": "A=1", ".db.env": "P=2"}

    u = StackUpdate(compose_yaml="services: {}\n", env_files={".env": "A=1"})
    assert u.env_files == {".env": "A=1"}

    r = StackResponse(name="myapp", compose_yaml="services: {}\n",
                      env_files={".env": "A=1"})
    assert r.env_files == {".env": "A=1"}


def test_env_files_defaults_to_empty_map():
    c = StackCreate(name="myapp", compose_yaml="services: {}\n")
    assert c.env_files == {}

    u = StackUpdate(compose_yaml="services: {}\n")
    assert u.env_files == {}

    r = StackResponse(name="myapp", compose_yaml="services: {}\n")
    assert r.env_files == {}
