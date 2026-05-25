"""Root conftest — loads .env into os.environ before tests run.

Backends (t5_backend, llama_backend) read env vars via os.environ.get() at
call time, not at import time, so setting them here is sufficient.

.env is gitignored and never committed.  Use .env.example as the template.
"""

import os
from pathlib import Path


def _load_dotenv(env_path: Path) -> None:
    """Minimal .env loader — no external dependency required."""
    if not env_path.is_file():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Only set if not already present in environment (shell export wins)
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(Path(__file__).parent / ".env")
