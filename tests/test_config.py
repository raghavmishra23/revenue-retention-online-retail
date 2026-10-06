import pytest

from src import config


def test_settings_contain_dataset_slug() -> None:
    settings = config.load_settings()
    assert config.get(settings, "dataset.slug") == "mashlyn/online-retail-ii-uci"


def test_resolve_path_is_absolute_under_root() -> None:
    raw = config.resolve_path("raw")
    assert raw.is_absolute()
    assert raw.as_posix().endswith("data/raw")


def test_resolve_path_unknown_key_raises() -> None:
    with pytest.raises(KeyError, match="no_such_key"):
        config.resolve_path("no_such_key")


def test_require_env_missing_names_only_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    name = "SURELY_ABSENT_VARIABLE_XYZ"
    monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError) as excinfo:
        config.require_env(name)
    assert name in str(excinfo.value)
    assert "value" not in str(excinfo.value).lower()


def test_require_env_returns_set_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPELINE_TEST_VAR", "abc")
    assert config.require_env("PIPELINE_TEST_VAR") == "abc"
