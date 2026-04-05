"""
hatch_build.py  -  Hatchling build hook for llmfit.

Downloads the pre-built binary for the target platform from GitHub Releases,
verifies its SHA256 checksum, and injects it into the wheel via shared_scripts
so that the installer places it in the environment's scripts directory
(e.g. ``.venv/bin/llmfit``).  Also overrides the wheel platform tag so that
cross-platform wheels can be produced from a single Linux CI runner.

For editable installs (``uv sync``, ``uv run``), the same mechanism is used
so that ``find_llmfit_bin()`` works via ``sysconfig.get_path("scripts")``.

Environment variables
---------------------
LLMFIT_TARGET
    Target triple to build for (e.g. ``x86_64-unknown-linux-gnu``).
    If unset, the current machine's platform is auto-detected.  Set this
    explicitly when building for a platform other than the host.
LLMFIT_VERSION
    Upstream release tag to fetch, including the leading ``v``
    (e.g. ``v0.8.6``).  If unset, the latest GitHub release is fetched
    automatically.
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
import urllib.request
import zipfile
from pathlib import Path
from typing import Literal, NewType

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

GITHUB_API_LATEST = "https://api.github.com/repos/AlexsJones/llmfit/releases/latest"
GITHUB_DOWNLOAD_URL = "https://github.com/AlexsJones/llmfit/releases/download/{version_tag}/{filename}"
GITHUB_LICENSE_API_URL = "https://api.github.com/repos/AlexsJones/llmfit/license?ref={ref}"

# The SPDX identifier we claim in our LICENSE file for the upstream binary.
# If the upstream ever relicenses, this check will catch it and the build will fail.
CLAIMED_UPSTREAM_SPDX_ID = "MIT"

# target triple → (wheel_platform_tag, binary_name, is_zip)
TARGET_CONFIGS: dict[str, tuple[str, str, bool]] = {
    "x86_64-unknown-linux-gnu": ("manylinux_2_17_x86_64", "llmfit", False),
    "aarch64-unknown-linux-gnu": ("manylinux_2_17_aarch64", "llmfit", False),
    "x86_64-unknown-linux-musl": ("musllinux_1_2_x86_64", "llmfit", False),
    "aarch64-unknown-linux-musl": ("musllinux_1_2_aarch64", "llmfit", False),
    "x86_64-apple-darwin": ("macosx_10_12_x86_64", "llmfit", False),
    "aarch64-apple-darwin": ("macosx_11_0_arm64", "llmfit", False),
    "x86_64-pc-windows-msvc": ("win_amd64", "llmfit.exe", True),
    "aarch64-pc-windows-msvc": ("win_arm64", "llmfit.exe", True),
}

# Use the NewType system to prevent confusion between upstream and PyPI version strings.
UpstreamVersion = NewType("UpstreamVersion", str)  # e.g. "v0.8.6"
PyPIVersion = NewType("PyPIVersion", str)  # e.g. "0.8.6"

def _validate_upstream_version(upstream_version: str) -> UpstreamVersion:
    if not re.match(r"^v\d+\.\d+\.\d+$", upstream_version):
        raise ValueError(f"Invalid upstream version: {upstream_version!r}")
    return UpstreamVersion(upstream_version)


def _upstream_to_pypi(upstream_version: UpstreamVersion) -> PyPIVersion:
    return PyPIVersion(upstream_version.lstrip("v"))


def _pypi_to_upstream(pypi_version: PyPIVersion) -> UpstreamVersion:
    return UpstreamVersion(f"v{pypi_version}")


def get_version() -> PyPIVersion:
    """Return the PyPI package version.

    Called by hatchling's ``code`` version source (see ``[tool.hatch.version]``
    in pyproject.toml).

    Resolution order:

    1. ``LLMFIT_VERSION`` environment variable — must be an upstream tag with
       a leading ``v`` (e.g. ``v0.8.6``).  ``build_wheels.py`` sets this.
    2. Latest upstream release fetched from the GitHub API.
    """
    v = os.environ.get("LLMFIT_VERSION")
    if v:
        return _upstream_to_pypi(_validate_upstream_version(v))
    print("[llmfit] LLMFIT_VERSION not set; fetching latest release tag from GitHub")
    with urllib.request.urlopen(GITHUB_API_LATEST) as resp:
        tag = json.loads(resp.read())["tag_name"]
    return _upstream_to_pypi(_validate_upstream_version(tag))


def _detect_target() -> str:
    """Return the target triple for the current machine."""
    # TODO: This should be deduced from the core metadata provided by hatchling. If that is not possible (statically, not dynamically),
    # then we should improve this detection to cover musl and avoid default fallbacks that may be incorrect on third platforms.
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
        f"Cannot auto-detect target triple for platform {sys.platform!r}/{machine!r}. Set LLMFIT_TARGET explicitly.",
    )


def _download(url: str) -> bytes:
    print(f"  GET {url}")
    with urllib.request.urlopen(url) as resp:
        return resp.read()


def _extract(archive_bytes: bytes, binary_name: str, *, is_zip: bool) -> bytes:
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


def _fetch_binary(version_tag: UpstreamVersion, target: str) -> bytes:
    """Download, verify, and extract the binary for the given version and target."""
    _, binary_name, is_zip = TARGET_CONFIGS[target]
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
            f"SHA256 mismatch for {archive_filename}:\n  expected: {expected_hash}\n  actual:   {actual_hash}",
        )
    print(f"  SHA256 OK ({actual_hash[:16]}...)")

    binary_data = _extract(archive_bytes, binary_name, is_zip=is_zip)
    print(f"  Extracted {binary_name} ({len(binary_data):,} bytes)")
    return binary_data


def _verify_upstream_license(version_tag: UpstreamVersion) -> None:
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
            "Refusing to build while license cannot be verified.",
        ) from exc

    spdx_id = (data.get("license") or {}).get("spdx_id", "NOASSERTION")
    if spdx_id == "NOASSERTION":
        raise RuntimeError(
            f"GitHub could not identify the upstream license at tag {version_tag!r}. "
            f"Cannot verify our claim of {CLAIMED_UPSTREAM_SPDX_ID!r}. "
            "Refusing to build.",
        )
    if spdx_id != CLAIMED_UPSTREAM_SPDX_ID:
        raise RuntimeError(
            f"Upstream license mismatch at tag {version_tag!r}: "
            f"we claim {CLAIMED_UPSTREAM_SPDX_ID!r} but GitHub reports {spdx_id!r}. "
            "Update LICENSE and CLAIMED_UPSTREAM_SPDX_ID before building.",
        )
    print(f"  License OK (upstream SPDX: {spdx_id})")


class LlmfitBinaryBuildHook(BuildHookInterface):
    """Hatchling build hook that injects the llmfit binary into each wheel."""

    PLUGIN_NAME = "llmfit binary from GitHub releases"

    def initialize(self, version: Literal["editable", "release"], build_data: dict) -> None:  # noqa: ARG002
        """Download the platform binary and configure the wheel before it is built."""
        target = os.environ.get("LLMFIT_TARGET") or _detect_target()
        if target not in TARGET_CONFIGS:
            raise ValueError(
                f"Unknown LLMFIT_TARGET={target!r}. Must be one of: {sorted(TARGET_CONFIGS)}",
            )

        wheel_tag, binary_name, _ = TARGET_CONFIGS[target]
        # hatchling has already called get_version() to populate self.metadata.version
        upstream_version: UpstreamVersion = _pypi_to_upstream(PyPIVersion(self.metadata.version))

        print(f"[llmfit build hook] target={target}  version={upstream_version}  wheel tag=py3-none-{wheel_tag}")
        _verify_upstream_license(upstream_version)

        binary_data = _fetch_binary(upstream_version, target)

        # Write binary to a versioned subdirectory of downloaded_binaries/ (gitignored).
        bin_dir = Path(self.root) / "downloaded_binaries" / upstream_version
        bin_dir.mkdir(parents=True, exist_ok=True)
        bin_path = bin_dir / binary_name
        bin_path.write_bytes(binary_data)
        bin_path.chmod(0o755)

        # Place the binary in the wheel's scripts directory so that the
        # installer puts it in .venv/bin/ (or Scripts/ on Windows).
        build_data["shared_scripts"][str(bin_path)] = binary_name

        # Override the platform tag so cross-platform wheels get the right name.
        build_data["tag"] = f"py3-none-{wheel_tag}"
        build_data["pure_python"] = False
