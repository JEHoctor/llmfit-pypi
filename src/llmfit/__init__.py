from __future__ import annotations

import sys
from pathlib import Path


class LlmfitError(Exception):
    """Base class for llmfit exceptions."""


class BinaryNotFoundError(FileNotFoundError, LlmfitError):
    """Exception raised when the llmfit binary cannot be found."""

    def __init__(self, candidate: Path) -> None:
        super().__init__(
            f"llmfit binary not found at {candidate}. This may indicate a corrupt or pure-sdist installation."
        )


def find_llmfit_bin() -> Path:
    """Return the path to the llmfit binary bundled with this package."""
    bin_name = "llmfit.exe" if sys.platform == "win32" else "llmfit"
    candidate = Path(__file__).parent / "_bin" / bin_name
    if not candidate.is_file():
        raise BinaryNotFoundError(candidate)
    return candidate
