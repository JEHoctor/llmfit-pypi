"""Tests for the llmfit Python module (src/llmfit/)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import llmfit
from llmfit import __version__, find_llmfit_bin

# TODO: Should we run tests in CI? If editable builds involve very similar code paths to wheel builds then this could be useful.


def test_version_is_string() -> None:
    """Tests that __version__ is a string."""
    assert isinstance(__version__, str)


def test_version_not_empty() -> None:
    """Tests that __version__ is not an empty string."""
    assert __version__ != ""


def test_find_llmfit_bin_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests that find_llmfit_bin raises a BinaryNotFoundError when the binary is missing."""
    monkeypatch.setattr(Path, "is_file", lambda: False)
    with pytest.raises(llmfit.BinaryNotFoundError):
        find_llmfit_bin()


def test_binary_path_is_path() -> None:
    """Tests that find_llmfit_bin returns a Path object."""
    assert isinstance(find_llmfit_bin(), Path)


def test_binary_runs() -> None:
    """Tests that the llmfit binary runs successfully."""
    result = subprocess.run([find_llmfit_bin(), "--help"], capture_output=True, check=False)
    assert result.returncode == 0
