"""Check: DVC-tracked sample data is in a consistent state. Deliberately
read-only — `dvc status` only, never `dvc pull`/`checkout`/`push` from a
check script. `dvc pull` was found mid-project to delete a working-tree
directory it considered stale-linked (data/samples/raw/ — since fixed by
keeping that directory plain-git-tracked, not DVC-tracked, precisely
because it's small and must survive a bare `git clone` with no DVC remote
access); a check script re-running mutating DVC commands on every
invocation is not a risk worth reintroducing for what this check needs to
verify.

Usage: python -m scripts.checks.check_dvc
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from scripts.checks._common import CheckSuite

ROOT = Path(__file__).resolve().parent.parent.parent


def main() -> None:
    suite = CheckSuite("dvc")

    if shutil.which("dvc") is None:
        suite.skip("all dvc checks", "dvc not installed — pip install -r requirements-docs.txt")
        suite.exit()
        return

    if not (ROOT / ".dvc").exists():
        suite.skip("all dvc checks", "DVC not initialized in this repo (no .dvc/ directory)")
        suite.exit()
        return

    with suite.check("dvc status runs cleanly (read-only)"):
        result = subprocess.run(["dvc", "status"], cwd=ROOT, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr

    with suite.check("tracked .dvc files exist and reference real content"):
        dvc_files = list((ROOT / "data" / "samples").glob("*.dvc"))
        assert dvc_files, "no .dvc pointer files found under data/samples/"
        for f in dvc_files:
            content = f.read_text()
            assert "md5:" in content, f"{f} has no md5 hash — not a valid DVC pointer file"

    with suite.check("raw/ (irreplaceable source PDFs) is plain-git-tracked, NOT DVC-tracked"):
        # The one thing this check actively guards against regressing: if
        # raw/ ever gets `dvc add`-ed again, a fresh `git clone` (with no
        # access to this machine's local DVC remote) would silently lose the
        # only non-regenerable input this whole project depends on.
        raw_dvc = ROOT / "data" / "samples" / "raw.dvc"
        assert not raw_dvc.exists(), (
            "data/samples/raw.dvc exists — raw/ must stay plain git-tracked, "
            "not DVC-tracked, or a fresh clone loses the source PDFs entirely"
        )
        result = subprocess.run(
            ["git", "ls-files", "data/samples/raw/"], cwd=ROOT, capture_output=True, text=True
        )
        assert result.stdout.strip(), "data/samples/raw/ is not tracked by git at all"

    suite.exit()


if __name__ == "__main__":
    main()
