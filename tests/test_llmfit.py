"""Tests for the llmfit Python module (src/llmfit/)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import llmfit
from llmfit import __version__, find_llmfit_bin


def test_version_is_string() -> None:
    """Tests that __version__ is a string."""
    assert isinstance(__version__, str)


def test_version_not_empty() -> None:
    """Tests that __version__ is not an empty string."""
    assert __version__ != ""


def test_find_llmfit_bin_raises_when_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests that find_llmfit_bin raises FileNotFoundError when the binary cannot be found relative to __file__."""
    monkeypatch.setattr(llmfit, "__file__", str(tmp_path / "__init__.py"))
    with pytest.raises(FileNotFoundError):
        find_llmfit_bin()


def test_binary_path_is_path() -> None:
    """Tests that find_llmfit_bin returns a Path object."""
    assert isinstance(find_llmfit_bin(), Path)


def test_binary_runs() -> None:
    """Tests that the llmfit binary runs successfully."""
    result = subprocess.run([find_llmfit_bin(), "--help"], capture_output=True, check=False)
    assert result.returncode == 0
