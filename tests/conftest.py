from __future__ import annotations

import sys
from pathlib import Path

# Debe ejecutarse antes de importar tests que usan `api`, `tools`, etc.
_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from dotenv import load_dotenv


def pytest_configure() -> None:
    load_dotenv()
