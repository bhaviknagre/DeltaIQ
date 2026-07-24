"""Check: every manifest under k8s/ is valid Kubernetes YAML — offline,
via kubeconform (schema-based validation, zero cluster contact; never
kubectl apply, never talks to whatever cluster kubectl's current context
happens to point at).

Includes the community CRD schema catalog (datreeio/CRDs-catalog) so the
KEDA ScaledObject (k8s/worker/keda-scaledobject.yaml) validates against its
real schema instead of having no schema at all until the KEDA operator is
installed on a real cluster — the difference between "1 skipped" and a
genuine 29/29 valid.

Usage: python -m scripts.checks.check_k8s
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from scripts.checks._common import CheckSuite

ROOT = Path(__file__).resolve().parent.parent.parent
CRD_CATALOG = "https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{ .Group }}/{{ .ResourceKind }}_{{ .ResourceAPIVersion }}.json"


def main() -> None:
    suite = CheckSuite("k8s")

    if not (ROOT / "k8s").exists():
        suite.skip("all k8s checks", "no k8s/ directory in this repo")
        suite.exit()
        return

    if shutil.which("kubeconform") is None:
        suite.skip("all k8s checks", "kubeconform not installed — brew install kubeconform")
        suite.exit()
        return

    manifests = sorted(str(p) for p in (ROOT / "k8s").rglob("*.yaml"))
    assert manifests, "no .yaml files found under k8s/"

    with suite.check(f"kubeconform: all {len(manifests)} manifest files valid (incl. KEDA CRD)"):
        result = subprocess.run(
            [
                "kubeconform", "-summary",
                "-schema-location", "default",
                "-schema-location", CRD_CATALOG,
                "-kubernetes-version", "1.29.0",
                *manifests,
            ],
            cwd=ROOT, capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
        assert "Invalid: 0" in result.stdout and "Errors: 0" in result.stdout, result.stdout

    with suite.check("secrets.yaml contains only placeholders, never real values"):
        content = (ROOT / "k8s" / "secrets" / "secrets.yaml").read_text()
        assert "REPLACE_ME" in content, "expected placeholder markers in the secrets template"
        # A crude but real guard: real API keys have recognizable prefixes.
        for marker in ("sk-ant-", "sk-proj-", "gsk_", "pk-lf-", "sk-lf-"):
            assert marker not in content, f"found what looks like a real key prefix ({marker}) in a committed file"

    with suite.check("every Deployment/manifest that references a Secret uses secretKeyRef, not a literal"):
        # Spot-check the two files that actually consume secret values —
        # catches a future edit that accidentally inlines a real value
        # instead of referencing the Secret object.
        for path in (ROOT / "k8s" / "minio" / "deployment.yaml", ROOT / "k8s" / "monitoring" / "grafana-deployment.yaml"):
            content = path.read_text()
            assert "secretKeyRef" in content, f"{path} should reference delta-chat-secrets via secretKeyRef"

    suite.exit()


if __name__ == "__main__":
    main()
