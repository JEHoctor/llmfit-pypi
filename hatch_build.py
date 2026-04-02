"""
hatch_build.py  –  Hatchling build hook for llmfit.

Downloads the pre-built binary for the target platform from GitHub Releases,
verifies its SHA256 checksum, and injects it into the wheel at
llmfit/_bin/{binary_name}.  Also overrides the wheel platform tag so that
cross-platform wheels can be produced from a single Linux CI runner.

For editable installs (``uv sync``, ``uv run``), the binary is written
directly into ``src/llmfit/_bin/`` so that ``find_llmfit_bin()`` works
without a full wheel build.  The binary is cached there and re-downloaded
only when absent.

Environment variables
---------------------
LLMFIT_TARGET
    Target triple to build for (e.g. ``x86_64-unknown-linux-gnu``).
    If unset, the current machine's platform is auto-detected.  Set this
    explicitly when building for a platform other than the host.
LLMFIT_VERSION
    Upstream release tag to fetch for editable installs (e.g. ``v0.8.6``).
    If unset, the version is read from pyproject.toml, falling back to the
    latest GitHub release.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import re
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

GITHUB_API_LATEST = "https://api.github.com/repos/AlexsJones/llmfit/releases/latest"
GITHUB_DOWNLOAD_URL = (
    "https://github.com/AlexsJones/llmfit/releases/download/{version_tag}/{filename}"
)

GITHUB_LICENSE_API_URL = (
    "https://api.github.com/repos/AlexsJones/llmfit/license?ref={ref}"
)

# The SPDX identifier we claim in our LICENSE file for the upstream binary.
# If the upstream ever relicenses, this check will catch it and the build will fail.
CLAIMED_UPSTREAM_SPDX_ID = "MIT"

# target triple → (wheel_platform_tag, binary_name, is_zip)
TARGET_CONFIGS: dict[str, tuple[str, str, bool]] = {
    "x86_64-unknown-linux-gnu":   ("manylinux_2_17_x86_64",  "llmfit",     False),
    "aarch64-unknown-linux-gnu":  ("manylinux_2_17_aarch64", "llmfit",     False),
    "x86_64-unknown-linux-musl":  ("musllinux_1_2_x86_64",   "llmfit",     False),
    "aarch64-unknown-linux-musl": ("musllinux_1_2_aarch64",  "llmfit",     False),
    "x86_64-apple-darwin":        ("macosx_10_15_x86_64",    "llmfit",     False),
    "aarch64-apple-darwin":       ("macosx_11_0_arm64",      "llmfit",     False),
    "x86_64-pc-windows-msvc":     ("win_amd64",              "llmfit.exe", True),
    "aarch64-pc-windows-msvc":    ("win_arm64",              "llmfit.exe", True),
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


def _fetch_binary(version: str, target: str) -> bytes:
    """Download, verify, and extract the binary for the given version and target."""
    _, binary_name, is_zip = TARGET_CONFIGS[target]
    version_tag = f"v{version.lstrip('v')}"
    ext = ".zip" if is_zip else ".tar.gz"
    archive_filename = f"llmfit-{version_tag}-{target}{ext}"
    sha256_filename = f"{archive_filename}.sha256"

    archive_url = GITHUB_DOWNLOAD_URL.format(version_tag=version_tag, filename=archive_filename)
    sha256_url = GITHUB_DOWNLOAD_URL.format(version_tag=version_tag, filename=sha256_filename)

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
    return binary_data


def _verify_upstream_license(version_tag: str) -> None:
    """Fetch the upstream license via the GitHub API and confirm it matches our claim.

    Fails the build if the license cannot be retrieved or does not match
    ``CLAIMED_UPSTREAM_SPDX_ID``.
    """
    url = GITHUB_LICENSE_API_URL.format(ref=version_tag)
    print(f"  GET {url}")
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        raise RuntimeError(
            f"Could not retrieve upstream license from {url}: {exc}\n"
            "Refusing to build while license cannot be verified."
        ) from exc

    spdx_id = (data.get("license") or {}).get("spdx_id", "NOASSERTION")
    if spdx_id == "NOASSERTION":
        raise RuntimeError(
            f"GitHub could not identify the upstream license at tag {version_tag!r}. "
            f"Cannot verify our claim of {CLAIMED_UPSTREAM_SPDX_ID!r}. "
            "Refusing to build."
        )
    if spdx_id != CLAIMED_UPSTREAM_SPDX_ID:
        raise RuntimeError(
            f"Upstream license mismatch at tag {version_tag!r}: "
            f"we claim {CLAIMED_UPSTREAM_SPDX_ID!r} but GitHub reports {spdx_id!r}. "
            "Update LICENSE and CLAIMED_UPSTREAM_SPDX_ID before building."
        )
    print(f"  License OK (upstream SPDX: {spdx_id})")


class CustomBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:
        target = os.environ.get("LLMFIT_TARGET") or _detect_target()
        if target not in TARGET_CONFIGS:
            raise ValueError(
                f"Unknown LLMFIT_TARGET={target!r}. "
                f"Must be one of: {sorted(TARGET_CONFIGS)}"
            )

        wheel_tag, binary_name, _ = TARGET_CONFIGS[target]

        if version == "editable":
            self._install_editable_binary(target, binary_name)
            return

        print(f"[llmfit build hook] target={target}  wheel tag=py3-none-{wheel_tag}")
        _verify_upstream_license(f"v{version.lstrip('v')}")

        binary_data = _fetch_binary(version, target)

        # Write binary and version-stamped __init__.py to a temp dir.
        tmp_dir = Path(tempfile.mkdtemp())
        tmp_bin = tmp_dir / binary_name
        tmp_bin.write_bytes(binary_data)
        tmp_bin.chmod(0o755)

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

    def _install_editable_binary(self, target: str, binary_name: str) -> None:
        """Write the binary directly into src/llmfit/_bin/ for editable installs.

        The binary is cached — if it already exists it is not re-downloaded.
        """
        bin_dir = Path(self.root) / "src" / "llmfit" / "_bin"
        dest = bin_dir / binary_name
        if dest.is_file():
            print(f"[llmfit build hook] editable: binary already present at {dest}")
            return

        version = self._resolve_editable_version()
        print(f"[llmfit build hook] editable: target={target}  version={version}")

        binary_data = _fetch_binary(version, target)
        bin_dir.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(binary_data)
        dest.chmod(0o755)
        print(f"  Installed binary to {dest}")

    def _resolve_editable_version(self) -> str:
        """Determine which upstream version to download for an editable install."""
        if v := os.environ.get("LLMFIT_VERSION"):
            return v.lstrip("v")

        toml_path = Path(self.root) / "pyproject.toml"
        text = toml_path.read_text()
        m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
        if m and m.group(1) != "0.0.0":
            return m.group(1)

        print("[llmfit build hook] version is placeholder; fetching latest release tag")
        with urllib.request.urlopen(GITHUB_API_LATEST) as resp:
            return json.loads(resp.read())["tag_name"].lstrip("v")
