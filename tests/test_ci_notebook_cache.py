"""The CI notebook job's cache key names the plan's SHA-256; keep it
equal to the notebook's."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ci_cache_key_holds_the_notebooks_pinned_sha256():
    notebook = (ROOT / "examples" / "sumwere_creek.py").read_text(encoding="utf-8")
    pinned = re.search(r'^PLAN_SHA256 = "([0-9a-f]{64})"', notebook, re.M)
    assert pinned, "PLAN_SHA256 not found in examples/sumwere_creek.py"
    ci = (ROOT / ".github" / "workflows" / "ci.yaml").read_text(encoding="utf-8")
    assert f"key: sumwere-creek-{pinned.group(1)}" in ci
