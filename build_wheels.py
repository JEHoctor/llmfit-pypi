#!/usr/bin/env python3
"""
build_wheels.py  –  Download llmfit release archives and build PyPI platform wheels.

Usage:
    python build_wheels.py [--version v0.8.6] [--output-dir dist] [--targets TARGET,...]

If --version is omitted, auto-detects the latest release via the GitHub API.

This script uses only the Python standard library.

The generated wheels are "data" wheels: the binary is placed inside the
.data/scripts/ directory so that pip/uv installs it onto PATH.

Platform wheels built (8 total):
    x86_64-unknown-linux-gnu   -> manylinux_2_17_x86_64   (glibc Linux x86_64)
    aarch64-unknown-linux-gnu  -> manylinux_2_17_aarch64  (glibc Linux arm64)
    x86_64-unknown-linux-musl  -> musllinux_1_2_x86_64    (musl Linux x86_64)
    aarch64-unknown-linux-musl -> musllinux_1_2_aarch64   (musl Linux arm64)
    x86_64-apple-darwin        -> macosx_10_15_x86_64     (Intel macOS)
    aarch64-apple-darwin       -> macosx_11_0_arm64       (Apple Silicon macOS)
    x86_64-pc-windows-msvc     -> win_amd64               (Windows x86_64)
    aarch64-pc-windows-msvc    -> win_arm64               (Windows arm64)

Note: musl Linux wheels are built but are NOT auto-selected by the llmfit
meta-package (PEP 508 markers cannot distinguish glibc vs musl). Alpine/musl
users should install the musl wheel directly, e.g.:
    pip install llmfit-x86-64-unknown-linux-musl
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import re
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

GITHUB_API_URL = "https://api.github.com/repos/AlexsJones/llmfit/releases/latest"
GITHUB_DOWNLOAD_URL = (
    "https://github.com/AlexsJones/llmfit/releases/download/{version}/{filename}"
)

# (target_triple, pypi_package_suffix, wheel_platform_tag, binary_name, is_zip)
PLATFORMS: list[tuple[str, str, str, str, bool]] = [
    (
        "x86_64-unknown-linux-gnu",
        "x86-64-unknown-linux-gnu",
        "manylinux_2_17_x86_64",
        "llmfit",
        False,
    ),
    (
        "aarch64-unknown-linux-gnu",
        "aarch64-unknown-linux-gnu",
        "manylinux_2_17_aarch64",
        "llmfit",
        False,
    ),
    (
        "x86_64-unknown-linux-musl",
        "x86-64-unknown-linux-musl",
        "musllinux_1_2_x86_64",
        "llmfit",
        False,
    ),
    (
        "aarch64-unknown-linux-musl",
        "aarch64-unknown-linux-musl",
        "musllinux_1_2_aarch64",
        "llmfit",
        False,
    ),
    (
        "x86_64-apple-darwin",
        "x86-64-apple-darwin",
        "macosx_10_15_x86_64",
        "llmfit",
        False,
    ),
    (
        "aarch64-apple-darwin",
        "aarch64-apple-darwin",
        "macosx_11_0_arm64",
        "llmfit",
        False,
    ),
    (
        "x86_64-pc-windows-msvc",
        "x86-64-pc-windows-msvc",
        "win_amd64",
        "llmfit.exe",
        True,
    ),
    (
        "aarch64-pc-windows-msvc",
        "aarch64-pc-windows-msvc",
        "win_arm64",
        "llmfit.exe",
        True,
    ),
]


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read())


def download_bytes(url: str) -> bytes:
    print(f"    GET {url}")
    with urllib.request.urlopen(url) as resp:
        return resp.read()


# ---------------------------------------------------------------------------
# Wheel construction helpers
# ---------------------------------------------------------------------------


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def record_hash(data: bytes) -> str:
    """Return base64url-encoded SHA-256 for use in a wheel RECORD file (PEP 427)."""
    digest = hashlib.sha256(data).digest()
    return "sha256:" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def build_platform_wheel(
    version: str,
    pkg_suffix: str,
    wheel_tag: str,
    binary_name: str,
    binary_data: bytes,
    output_dir: Path,
) -> Path:
    """
    Construct a minimal platform wheel containing just the binary.

    The binary is written to {name}-{version}.data/scripts/ so that pip/uv
    installs it onto PATH (PEP 427 data section).
    """
    pkg_name = f"llmfit-{pkg_suffix}"
    # Wheel filenames normalise '-' to '_'
    pkg_norm = pkg_name.replace("-", "_")

    dist_info = f"{pkg_norm}-{version}.dist-info"
    dist_data = f"{pkg_norm}-{version}.data"
    script_path = f"{dist_data}/scripts/{binary_name}"

    metadata = (
        f"Metadata-Version: 2.1\n"
        f"Name: {pkg_name}\n"
        f"Version: {version}\n"
        f"Summary: llmfit binary for {pkg_suffix}\n"
        f"Home-page: https://github.com/AlexsJones/llmfit\n"
        f"License: MIT\n"
        f"Requires-Python: >=3.8\n"
    ).encode()

    wheel_meta = (
        f"Wheel-Version: 1.0\n"
        f"Generator: build_wheels.py\n"
        f"Root-Is-Purelib: false\n"
        f"Tag: py3-none-{wheel_tag}\n"
    ).encode()

    # RECORD is a CSV listing every file with its hash and size.
    # The RECORD entry for RECORD itself always has empty hash and size fields.
    record_buf = io.StringIO()
    w = csv.writer(record_buf)
    w.writerow([script_path, record_hash(binary_data), str(len(binary_data))])
    w.writerow([f"{dist_info}/METADATA", record_hash(metadata), str(len(metadata))])
    w.writerow([f"{dist_info}/WHEEL", record_hash(wheel_meta), str(len(wheel_meta))])
    w.writerow([f"{dist_info}/RECORD", "", ""])
    record_content = record_buf.getvalue().encode()

    wheel_filename = f"{pkg_norm}-{version}-py3-none-{wheel_tag}.whl"
    wheel_path = output_dir / wheel_filename

    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Set Unix execute bits on the binary via external_attr so pip marks it
        # executable after installation.
        zi = zipfile.ZipInfo(script_path)
        zi.external_attr = (0o755 & 0xFFFF) << 16
        zf.writestr(zi, binary_data)

        zf.writestr(f"{dist_info}/METADATA", metadata)
        zf.writestr(f"{dist_info}/WHEEL", wheel_meta)
        zf.writestr(f"{dist_info}/RECORD", record_content)

    return wheel_path


# ---------------------------------------------------------------------------
# Archive extraction
# ---------------------------------------------------------------------------


def extract_binary(archive_bytes: bytes, binary_name: str, is_zip: bool) -> bytes:
    """Extract a named binary from a .tar.gz or .zip archive."""
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


# ---------------------------------------------------------------------------
# Version management
# ---------------------------------------------------------------------------


def get_latest_tag() -> str:
    """Return the latest upstream release tag (e.g. 'v0.8.6')."""
    data = fetch_json(GITHUB_API_URL)
    return data["tag_name"]


def update_meta_package_version(version: str) -> None:
    """Rewrite the version field in pyproject.toml to match upstream."""
    toml_path = Path(__file__).parent / "pyproject.toml"
    text = toml_path.read_text()
    updated = re.sub(
        r'^(version\s*=\s*")[^"]*(")',
        rf'\g<1>{version}\2',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if updated == text:
        print(f"  WARNING: version field not found in {toml_path}")
    else:
        toml_path.write_text(updated)
        print(f"  Updated pyproject.toml version -> {version}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build PyPI platform wheels for llmfit.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--version",
        metavar="TAG",
        help="Upstream release tag to package (e.g. v0.8.6). Defaults to latest.",
    )
    parser.add_argument(
        "--output-dir",
        default="dist",
        metavar="DIR",
        help="Directory to write wheels into (default: dist).",
    )
    parser.add_argument(
        "--targets",
        metavar="T1,T2,...",
        help="Comma-separated subset of target triples to build. Default: all.",
    )
    args = parser.parse_args()

    version_tag: str = args.version or get_latest_tag()
    version = version_tag.lstrip("v")
    print(f"Building llmfit {version} (upstream tag: {version_tag})\n")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    targets_filter: set[str] | None = (
        set(args.targets.split(",")) if args.targets else None
    )

    update_meta_package_version(version)

    built: list[Path] = []
    errors: list[str] = []

    for target, pkg_suffix, wheel_tag, binary_name, is_zip in PLATFORMS:
        if targets_filter and target not in targets_filter:
            continue

        ext = ".zip" if is_zip else ".tar.gz"
        archive_filename = f"llmfit-{version_tag}-{target}{ext}"
        sha256_filename = f"{archive_filename}.sha256"

        print(f"[{target}]")

        archive_url = GITHUB_DOWNLOAD_URL.format(
            version=version_tag, filename=archive_filename
        )
        sha256_url = GITHUB_DOWNLOAD_URL.format(
            version=version_tag, filename=sha256_filename
        )

        try:
            archive_bytes = download_bytes(archive_url)
            sha256_file_content = download_bytes(sha256_url).decode()
            # The .sha256 file contains "<hex>  <filename>" or just "<hex>"
            expected_hash = sha256_file_content.split()[0]

            actual_hash = sha256_hex(archive_bytes)
            if actual_hash != expected_hash:
                raise ValueError(
                    f"SHA256 mismatch!\n"
                    f"  expected: {expected_hash}\n"
                    f"  actual:   {actual_hash}"
                )
            print(f"    SHA256 OK ({actual_hash[:16]}...)")

            binary_data = extract_binary(archive_bytes, binary_name, is_zip)
            print(f"    Extracted {binary_name} ({len(binary_data):,} bytes)")

            wheel_path = build_platform_wheel(
                version, pkg_suffix, wheel_tag, binary_name, binary_data, output_dir
            )
            print(f"    -> {wheel_path.name}\n")
            built.append(wheel_path)

        except Exception as exc:
            print(f"    ERROR: {exc}\n", file=sys.stderr)
            errors.append(f"{target}: {exc}")

    print(f"Built {len(built)} wheel(s) in {output_dir}/")
    if errors:
        print(f"\n{len(errors)} error(s):")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
