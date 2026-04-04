from __future__ import annotations

import os
import sys

from llmfit import find_llmfit_bin


def main() -> None:
    """Entry point for the llmfit CLI (used by [project.scripts])."""
    bin_path = str(find_llmfit_bin())
    args = [bin_path, *sys.argv[1:]]
    if sys.platform == "win32":
        import subprocess  # noqa: PLC0415

        # TODO: suppress traceback on interrupt like:
        # https://github.com/astral-sh/ruff/blob/main/python/ruff/__main__.py

        sys.exit(subprocess.run(args, check=False).returncode)
    else:
        # TODO: os.execv is the right choice, but we need to ensure that the bin_path is absolute.
        os.execv(bin_path, args)  # noqa: S606 # arguments are sufficiently validated


if __name__ == "__main__":
    main()
