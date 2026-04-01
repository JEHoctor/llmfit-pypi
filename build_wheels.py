#!/usr/bin/env python3
"""
build_wheels.py  –  Download llmfit release archives and build PyPI platform wheels.

Usage:
    python build_wheels.py [--version v0.8.6] [--output-dir dist] [--targets TARGET,...]

If --version is omitted, auto-detects the latest release via the GitHub API.

This script uses only the Python standard library.

Each wheel is a self-contained platform wheel for the single 'llmfit' package.
The binary is placed at llmfit/_bin/llmfit (or llmfit.exe on Windows) inside the
wheel, and a [project.scripts] entry_points.txt wires 'llmfit' → llmfit.__main__:main.
pip/uv selects the correct wheel automatically based on platform tags.

Platform wheels built (8 total):
    x86_64-unknown-linux-gnu   -> manylinux_2_17_x86_64   (glibc Linux x86_64)
    aarch64-unknown-linux-gnu  -> manylinux_2_17_aarch64  (glibc Linux arm64)
    x86_64-unknown-linux-musl  -> musllinux_1_2_x86_64    (musl Linux x86_64)
    aarch64-unknown-linux-musl -> musllinux_1_2_aarch64   (musl Linux arm64)
    x86_64-apple-darwin        -> macosx_10_15_x86_64     (Intel macOS)
    aarch64-apple-darwin       -> macosx_11_0_arm64       (Apple Silicon macOS)
    x86_64-pc-windows-msvc     -> win_amd64               (Windows x86_64)
    aarch64-pc-windows-msvc    -> win_arm64               (Windows arm64)

musl Linux wheels are now auto-selected by pip on musl systems via the
musllinux platform tag — no manual installation needed.
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

# (target_triple, wheel_platform_tag, binary_name, is_zip)
PLATFORMS: list[tuple[str, str, str, bool]] = [
    (
        "x86_64-unknown-linux-gnu",
        "manylinux_2_17_x86_64",
        "llmfit",
        False,
    ),
    (
        "aarch64-unknown-linux-gnu",
        "manylinux_2_17_aarch64",
        "llmfit",
        False,
    ),
    (
        "x86_64-unknown-linux-musl",
        "musllinux_1_2_x86_64",
        "llmfit",
        False,
    ),
    (
        "aarch64-unknown-linux-musl",
        "musllinux_1_2_aarch64",
        "llmfit",
        False,
    ),
    (
        "x86_64-apple-darwin",
        "macosx_10_15_x86_64",
        "llmfit",
        False,
    ),
    (
        "aarch64-apple-darwin",
        "macosx_11_0_arm64",
        "llmfit",
        False,
    ),
    (
        "x86_64-pc-windows-msvc",
        "win_amd64",
        "llmfit.exe",
        True,
    ),
    (
        "aarch64-pc-windows-msvc",
        "win_arm64",
        "llmfit.exe",
        True,
    ),
]

ENTRY_POINTS = b"[console_scripts]\nllmfit = llmfit.__main__:main\n"


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
    wheel_tag: str,
    binary_name: str,
    binary_data: bytes,
    init_py: bytes,
    main_py: bytes,
    output_dir: Path,
) -> Path:
    """
    Construct a platform wheel for the 'llmfit' package.

    Layout inside the wheel:
        llmfit/__init__.py
        llmfit/__main__.py
        llmfit/_bin/{binary_name}       ← the pre-built CLI binary
        llmfit-{version}.dist-info/METADATA
        llmfit-{version}.dist-info/WHEEL
        llmfit-{version}.dist-info/entry_points.txt
        llmfit-{version}.dist-info/RECORD
    """
    dist_info = f"llmfit-{version}.dist-info"
    bin_path = f"llmfit/_bin/{binary_name}"

    metadata = (
        f"Metadata-Version: 2.1\n"
        f"Name: llmfit\n"
        f"Version: {version}\n"
        f"Summary: Unofficial PyPI distribution of llmfit – the LLM model management CLI\n"
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

    record_buf = io.StringIO()
    w = csv.writer(record_buf)
    w.writerow([bin_path, record_hash(binary_data), str(len(binary_data))])
    w.writerow(["llmfit/__init__.py", record_hash(init_py), str(len(init_py))])
    w.writerow(["llmfit/__main__.py", record_hash(main_py), str(len(main_py))])
    w.writerow([f"{dist_info}/METADATA", record_hash(metadata), str(len(metadata))])
    w.writerow([f"{dist_info}/WHEEL", record_hash(wheel_meta), str(len(wheel_meta))])
    w.writerow(
        [
            f"{dist_info}/entry_points.txt",
            record_hash(ENTRY_POINTS),
            str(len(ENTRY_POINTS)),
        ]
    )
    w.writerow([f"{dist_info}/RECORD", "", ""])
    record_content = record_buf.getvalue().encode()

    wheel_filename = f"llmfit-{version}-py3-none-{wheel_tag}.whl"
    wheel_path = output_dir / wheel_filename

    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Set Unix execute bits on the binary.
        zi = zipfile.ZipInfo(bin_path)
        zi.external_attr = (0o755 & 0xFFFF) << 16
        zf.writestr(zi, binary_data)

        zf.writestr("llmfit/__init__.py", init_py)
        zf.writestr("llmfit/__main__.py", main_py)
        zf.writestr(f"{dist_info}/METADATA", metadata)
        zf.writestr(f"{dist_info}/WHEEL", wheel_meta)
        zf.writestr(f"{dist_info}/entry_points.txt", ENTRY_POINTS)
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


def update_pyproject_version(version: str) -> None:
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


def load_python_sources(version: str) -> tuple[bytes, bytes]:
    """
    Read __init__.py and __main__.py from src/llmfit/, substituting the
    placeholder version string with the actual release version.
    Returns (init_py_bytes, main_py_bytes).
    """
    src = Path(__file__).parent / "src" / "llmfit"

    init_text = (src / "__init__.py").read_text()
    init_text = init_text.replace('__version__ = "0.0.0"', f'__version__ = "{version}"', 1)

    main_text = (src / "__main__.py").read_text()

    return init_text.encode(), main_text.encode()


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

    update_pyproject_version(version)
    init_py, main_py = load_python_sources(version)

    built: list[Path] = []
    errors: list[str] = []

    for target, wheel_tag, binary_name, is_zip in PLATFORMS:
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
                version, wheel_tag, binary_name, binary_data, init_py, main_py, output_dir
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
