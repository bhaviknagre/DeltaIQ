"""Check: the MkDocs documentation site builds cleanly with --strict (fails
on broken internal links/refs, not just Python exceptions).

Usage: python -m scripts.checks.check_docs
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from scripts.checks._common import CheckSuite

ROOT = Path(__file__).resolve().parent.parent.parent


def main() -> None:
    suite = CheckSuite("docs")

    if shutil.which("mkdocs") is None:
        suite.skip("mkdocs build --strict", "mkdocs not installed — pip install -r requirements-docs.txt")
        suite.exit()
        return

    with suite.check("mkdocs build --strict succeeds"):
        result = subprocess.run(
            ["mkdocs", "build", "--strict", "--site-dir", "site"],
            cwd=ROOT, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr[-1500:]

    shutil.rmtree(ROOT / "site", ignore_errors=True)

    suite.exit()


if __name__ == "__main__":
    main()
