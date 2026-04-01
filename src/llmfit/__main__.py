from __future__ import annotations

import os
import sys

from llmfit import find_llmfit_bin


def main() -> None:
    """Entry point for the llmfit CLI (used by [project.scripts])."""
    bin_path = str(find_llmfit_bin())
    args = [bin_path] + sys.argv[1:]
    if sys.platform == "win32":
        import subprocess

        sys.exit(subprocess.run(args).returncode)
    else:
        os.execv(bin_path, args)


if __name__ == "__main__":
    main()
