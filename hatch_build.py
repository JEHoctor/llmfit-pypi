"""
hatch_build.py  –  Hatchling build hook for llmfit.

Downloads the pre-built binary for the target platform from GitHub Releases,
verifies its SHA256 checksum, and injects it into the wheel at
llmfit/_bin/{binary_name}.  Also overrides the wheel platform tag so that
cross-platform wheels can be produced from a single Linux CI runner.

Environment variables
---------------------
LLMFIT_TARGET
    Target triple to build for (e.g. ``x86_64-unknown-linux-gnu``).
    If unset, the current machine's platform is auto-detected.  Set this
    explicitly when building for a platform other than the host.
"""
from __future__ import annotations

import hashlib
import io
import platform
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
import os
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

GITHUB_DOWNLOAD_URL = (
    "https://github.com/AlexsJones/llmfit/releases/download/{version_tag}/{filename}"
)

# target triple → (wheel_platform_tag, binary_name, is_zip)
TARGET_CONFIGS: dict[str, tuple[str, str, bool]] = {
    "x86_64-unknown-linux-gnu":  ("manylinux_2_17_x86_64",  "llmfit",     False),
    "aarch64-unknown-linux-gnu": ("manylinux_2_17_aarch64", "llmfit",     False),
    "x86_64-unknown-linux-musl": ("musllinux_1_2_x86_64",   "llmfit",     False),
    "aarch64-unknown-linux-musl":("musllinux_1_2_aarch64",  "llmfit",     False),
    "x86_64-apple-darwin":       ("macosx_10_15_x86_64",    "llmfit",     False),
    "aarch64-apple-darwin":      ("macosx_11_0_arm64",      "llmfit",     False),
    "x86_64-pc-windows-msvc":    ("win_amd64",              "llmfit.exe", True),
    "aarch64-pc-windows-msvc":   ("win_arm64",              "llmfit.exe", True),
}


def _detect_target() -> str:
    """Return the target triple for the current machine."""
    machine = platform.machine().lower()
    if sys.platform.startswith("linux"):
        arch = "x86_64" if machine in ("x86_64", "amd64") else "aarch64"
        return f"{arch}-unknown-linux-gnu"
    if sys.platform == "darwin":
        arch = "x86_64" if machine == "x86_64" else "aarch64"
        return f"{arch}-apple-darwin"
    if sys.platform == "win32":
        arch = "x86_64" if machine in ("amd64", "x86_64") else "aarch64"
        return f"{arch}-pc-windows-msvc"
    raise RuntimeError(
        f"Cannot auto-detect target triple for platform {sys.platform!r}/{machine!r}. "
        "Set LLMFIT_TARGET explicitly."
    )


def _download(url: str) -> bytes:
    print(f"  GET {url}")
    with urllib.request.urlopen(url) as resp:
        return resp.read()


def _extract(archive_bytes: bytes, binary_name: str, is_zip: bool) -> bytes:
    if is_zip:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
            for name in zf.namelist():
                if Path(name).name == binary_name:
                    return zf.read(name)
        raise FileNotFoundError(f"{binary_name!r} not found in zip archive")
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tf:
        for member in tf.getmembers():
            if Path(member.name).name == binary_name:
                f = tf.extractfile(member)
                if f is not None:
                    return f.read()
    raise FileNotFoundError(f"{binary_name!r} not found in tar.gz archive")


class CustomBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:
        target = os.environ.get("LLMFIT_TARGET") or _detect_target()
        if target not in TARGET_CONFIGS:
            raise ValueError(
                f"Unknown LLMFIT_TARGET={target!r}. "
                f"Must be one of: {sorted(TARGET_CONFIGS)}"
            )

        wheel_tag, binary_name, is_zip = TARGET_CONFIGS[target]
        version_tag = f"v{version.lstrip('v')}"
        ext = ".zip" if is_zip else ".tar.gz"
        archive_filename = f"llmfit-{version_tag}-{target}{ext}"
        sha256_filename = f"{archive_filename}.sha256"

        print(f"[llmfit build hook] target={target}  wheel tag=py3-none-{wheel_tag}")

        archive_url = GITHUB_DOWNLOAD_URL.format(
            version_tag=version_tag, filename=archive_filename
        )
        sha256_url = GITHUB_DOWNLOAD_URL.format(
            version_tag=version_tag, filename=sha256_filename
        )

        archive_bytes = _download(archive_url)
        sha256_content = _download(sha256_url).decode()
        expected_hash = sha256_content.split()[0]
        actual_hash = hashlib.sha256(archive_bytes).hexdigest()
        if actual_hash != expected_hash:
            raise ValueError(
                f"SHA256 mismatch for {archive_filename}:\n"
                f"  expected: {expected_hash}\n"
                f"  actual:   {actual_hash}"
            )
        print(f"  SHA256 OK ({actual_hash[:16]}...)")

        binary_data = _extract(archive_bytes, binary_name, is_zip)
        print(f"  Extracted {binary_name} ({len(binary_data):,} bytes)")

        # Write binary to a temp dir that persists for the duration of the build.
        tmp_dir = Path(tempfile.mkdtemp())
        tmp_bin = tmp_dir / binary_name
        tmp_bin.write_bytes(binary_data)
        tmp_bin.chmod(0o755)

        # Inject binary and override __init__.py with the correct __version__.
        init_src = Path(self.root) / "src" / "llmfit" / "__init__.py"
        init_text = init_src.read_text().replace(
            '__version__ = "0.0.0"', f'__version__ = "{version}"', 1
        )
        tmp_init = tmp_dir / "__init__.py"
        tmp_init.write_text(init_text)

        build_data["force_include"][str(tmp_bin)] = f"llmfit/_bin/{binary_name}"
        build_data["force_include"][str(tmp_init)] = "llmfit/__init__.py"

        # Override the platform tag so cross-platform wheels get the right name.
        build_data["tag"] = f"py3-none-{wheel_tag}"
        build_data["pure_python"] = False
