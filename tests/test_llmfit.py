"""Tests for the llmfit Python module (src/llmfit/)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import llmfit
from llmfit import find_llmfit_bin


def test_find_llmfit_bin_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests that find_llmfit_bin raises a BinaryNotFoundError when the binary is missing."""
    monkeypatch.setattr(Path, "is_file", lambda _: False)
    with pytest.raises(llmfit.BinaryNotFoundError):
        find_llmfit_bin()


def test_binary_path_is_path() -> None:
    """Tests that find_llmfit_bin returns a Path object."""
    assert isinstance(find_llmfit_bin(), Path)


def test_binary_runs() -> None:
    """Tests that the llmfit binary runs successfully."""
    result = subprocess.run([find_llmfit_bin(), "--help"], capture_output=True, check=False)
    assert result.returncode == 0
