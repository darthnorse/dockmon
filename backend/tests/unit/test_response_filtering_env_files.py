from utils.response_filtering import filter_stack_env_files


def test_returns_map_when_authorized():
    files = {".env": "A=1", ".db.env": "P=secret"}
    assert filter_stack_env_files(files, can_view_env=True) == files


def test_returns_empty_when_not_authorized():
    files = {".env": "A=1", ".db.env": "P=secret"}
    assert filter_stack_env_files(files, can_view_env=False) == {}


def test_none_input_returns_empty_map():
    assert filter_stack_env_files(None, can_view_env=True) == {}
