import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yml"
FILE_PATH_KEYS = ("warehouse", "excel_audit")

_env_loaded = False


@lru_cache(maxsize=None)
def _read_settings(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_settings(path: Path | None = None) -> dict[str, Any]:
    return _read_settings(path or SETTINGS_PATH)


def get(settings: dict[str, Any], dotted_key: str) -> Any:
    node: Any = settings
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(f"unknown setting: {dotted_key}")
        node = node[part]
    return node


def resolve_path(key: str) -> Path:
    paths = load_settings()["paths"]
    if key not in paths:
        raise KeyError(f"unknown path key: {key}")
    return PROJECT_ROOT / paths[key]


def require_env(name: str) -> str:
    global _env_loaded
    if not _env_loaded:
        load_dotenv(PROJECT_ROOT / ".env")
        _env_loaded = True
    if name not in os.environ:
        raise RuntimeError(f"missing environment variable: {name}")
    return os.environ[name]


def ensure_directories() -> None:
    for key in load_settings()["paths"]:
        target = resolve_path(key)
        (target.parent if key in FILE_PATH_KEYS else target).mkdir(parents=True, exist_ok=True)
