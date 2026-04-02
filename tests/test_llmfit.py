"""Tests for the llmfit Python module (src/llmfit/)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import llmfit
from llmfit import __version__, find_llmfit_bin


def test_version_is_string():
    assert isinstance(__version__, str)


def test_version_not_empty():
    assert __version__ != ""


def test_find_llmfit_bin_raises_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(llmfit, "__file__", str(tmp_path / "__init__.py"))
    with pytest.raises(FileNotFoundError):
        find_llmfit_bin()


def test_binary_path_is_path():
    assert isinstance(find_llmfit_bin(), Path)


def test_binary_runs():
    result = subprocess.run([find_llmfit_bin(), "--help"], capture_output=True)
    assert result.returncode == 0
