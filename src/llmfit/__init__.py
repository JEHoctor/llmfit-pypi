from __future__ import annotations

import sys
from pathlib import Path

__version__ = "0.0.0"


def find_llmfit_bin() -> Path:
    """Return the path to the llmfit binary bundled with this package."""
    bin_name = "llmfit.exe" if sys.platform == "win32" else "llmfit"
    candidate = Path(__file__).parent / "_bin" / bin_name
    if not candidate.is_file():
        raise FileNotFoundError(
            f"llmfit binary not found at {candidate}. This may indicate a corrupt or pure-sdist installation.",
        )
    return candidate
