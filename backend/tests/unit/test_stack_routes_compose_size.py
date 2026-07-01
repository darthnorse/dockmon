"""StackCreate and StackUpdate reject compose_yaml exceeding 1 MB."""
import pytest
from pydantic import ValidationError

from deployment.stack_routes import StackCreate, StackUpdate


def test_stack_create_rejects_oversized_compose_yaml():
    oversized = "A" * (1024 * 1024 + 1)
    with pytest.raises(ValidationError):
        StackCreate(name="x", compose_yaml=oversized)


def test_stack_update_rejects_oversized_compose_yaml():
    oversized = "A" * (1024 * 1024 + 1)
    with pytest.raises(ValidationError):
        StackUpdate(compose_yaml=oversized)


def test_stack_create_accepts_compose_yaml_at_limit():
    at_limit = "A" * (1024 * 1024)
    obj = StackCreate(name="x", compose_yaml=at_limit)
    assert len(obj.compose_yaml) == 1024 * 1024


def test_stack_update_accepts_compose_yaml_at_limit():
    at_limit = "A" * (1024 * 1024)
    obj = StackUpdate(compose_yaml=at_limit)
    assert len(obj.compose_yaml) == 1024 * 1024
