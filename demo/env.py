"""Optional .env loading for demo and example entry points.

The SDK itself reads plain environment variables and never loads
files; entry points call load_local_env() so a local, gitignored .env
(copied from .env.example) supplies Qwen credentials automatically.
Existing environment variables always win — .env never overrides them.
"""

from __future__ import annotations

from pathlib import Path


def load_local_env() -> bool:
    """Load ./.env (working directory) if python-dotenv is installed.

    Returns True when a .env file was found and loaded; False when the
    file is absent or python-dotenv is not installed. Never raises and
    never overrides variables already present in the environment.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return False
    env_file = Path.cwd() / ".env"
    if not env_file.is_file():
        return False
    return load_dotenv(env_file, override=False)
