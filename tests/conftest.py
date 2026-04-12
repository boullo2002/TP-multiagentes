from __future__ import annotations

import sys
from pathlib import Path

# --- Path (antes de importar módulos de la app)
_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv  # noqa: E402

# spec-tests.md §3: cargar .env desde la raíz antes de importar la app
_env_ok = load_dotenv(_ROOT / ".env") or load_dotenv(_ROOT / ".env.example")
assert _env_ok, (
    "Falta .env en la raíz del repo; copiá desde .env.example (spec-tests: load_dotenv)."
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def settings():
    """Objeto de settings (pydantic-settings) ya con env cargado."""
    from config.settings import get_settings

    return get_settings()


@pytest.fixture
def client() -> TestClient:
    """TestClient FastAPI (spec-tests §3)."""
    from api.main import get_app

    return TestClient(get_app())


@pytest.fixture
def tmp_data_dir(monkeypatch, tmp_path: Path):
    """DATA_DIR aislado + cache de settings limpiado."""
    from config.settings import get_settings

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()
