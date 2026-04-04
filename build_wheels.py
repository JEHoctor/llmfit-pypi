"""
build_wheels.py  -  Build all llmfit platform wheels via `uv build`.

Usage:
    python build_wheels.py [--version v0.8.6] [--output-dir dist] [--targets TARGET,...]

If --version is omitted, the latest upstream release tag is fetched from the
GitHub API.

For each target, this script sets LLMFIT_TARGET and calls `uv build --wheel`.
The hatch_build.py hook handles downloading the binary, verifying its SHA256,
and injecting it into the wheel with the correct platform tag.

Run `uv build --wheel` directly (without this script) to build a wheel for
the current machine only — useful for local testing with pytest.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

GITHUB_API_URL = "https://api.github.com/repos/AlexsJones/llmfit/releases/latest"

TARGETS = [
    "x86_64-unknown-linux-gnu",
    "aarch64-unknown-linux-gnu",
    "x86_64-unknown-linux-musl",
    "aarch64-unknown-linux-musl",
    "x86_64-apple-darwin",
    "aarch64-apple-darwin",
    "x86_64-pc-windows-msvc",
    "aarch64-pc-windows-msvc",
]


def get_latest_tag() -> str:
    """Fetch the latest upstream release tag from the GitHub API."""
    with urllib.request.urlopen(GITHUB_API_URL) as resp:
        return json.loads(resp.read())["tag_name"]


def update_pyproject_version(version: str) -> None:
    """Rewrite the version field in pyproject.toml to match the upstream release."""
    toml_path = Path(__file__).parent / "pyproject.toml"
    text = toml_path.read_text()
    updated = re.sub(
        r'^(version\s*=\s*")[^"]*(")',
        rf"\g<1>{version}\2",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if updated == text:
        raise RuntimeError(f"Version field not found in {toml_path}")
    toml_path.write_text(updated)
    print(f"  Updated pyproject.toml version -> {version}")


def main() -> None:
    """Parse arguments and build wheels for all target platforms."""
    parser = argparse.ArgumentParser(
        description="Build all llmfit platform wheels via uv build.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--version",
        metavar="TAG",
        help="Upstream release tag (e.g. v0.8.6). Defaults to latest.",
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
        help="Comma-separated subset of targets. Default: all.",
    )
    args = parser.parse_args()

    version_tag: str = args.version or get_latest_tag()
    version = version_tag.lstrip("v")
    print(f"Building llmfit {version} (upstream tag: {version_tag})\n")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    targets = args.targets.split(",") if args.targets else TARGETS

    update_pyproject_version(version)
    print()

    errors: list[str] = []
    for target in targets:
        print(f"[{target}]")
        env = {**os.environ, "LLMFIT_TARGET": target}
        result = subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(output_dir)],  # noqa: S607 # We do want to use the uv found on the PATH.
            env=env,
            check=False,
        )
        if result.returncode != 0:
            errors.append(target)
            print("  FAILED\n", file=sys.stderr)
        else:
            print()

    print(f"Built {len(targets) - len(errors)}/{len(targets)} wheel(s) in {output_dir}/")
    if errors:
        print(f"\n{len(errors)} error(s): {', '.join(errors)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
