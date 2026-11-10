"""Where config and state live. Everything is overridable by env vars for tests and simulation."""

import os
from pathlib import Path

_MARKER = Path("config") / "athlete_context.json"


def repo_root() -> Path:
    env = os.environ.get("COACH_HOME")
    if env:
        return Path(env)
    here = Path.cwd()
    for candidate in [here, *here.parents]:
        if (candidate / _MARKER).exists():
            return candidate
    return Path(__file__).resolve().parents[2]


def config_dir() -> Path:
    return repo_root() / "config"


def state_dir() -> Path:
    env = os.environ.get("COACH_STATE_DIR")
    return Path(env) if env else repo_root() / "state"


def demo_dir() -> Path:
    """Bundled demo athlete: config + fixtures used by tests and `coach simulate`."""
    return Path(__file__).resolve().parent / "demo"


def fixtures_dir() -> Path:
    return demo_dir() / "fixtures"


def demo_config_dir() -> Path:
    return demo_dir() / "config"


def is_mock() -> bool:
    return os.environ.get("COACH_MOCK", "").lower() in {"1", "true", "yes"}
