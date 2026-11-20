"""Publication requires matching public CI evidence, never an unrelated success."""
import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("ruamel.yaml")
TOOLS = Path(__file__).resolve().parents[4] / "tools"
spec = importlib.util.spec_from_file_location("public_check", TOOLS / "check_public_package.py")
checker = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(TOOLS))
try:
    spec.loader.exec_module(checker)
finally:
    sys.path.remove(str(TOOLS))


def status(state="success", fingerprint="abc", creator="github-actions[bot]"):
    return {"state": state, "context": "esp-iris/package/" + fingerprint,
            "creator": {"login": creator}}


@pytest.mark.parametrize("statuses,expected", [
    ([status()], True),
    ([status(fingerprint="another-package")], False),
    ([status(creator="human")], False),
    ([status("pending"), status()], False),
    ([status("failure"), status()], False),
    ([status(), status("failure")], True),
    ([], False),
])
def test_only_latest_trusted_status_for_matching_content_is_accepted(statuses, expected):
    assert checker.successful_status(statuses, "abc") is expected


def test_unmatched_public_run_cannot_authorize_release(tmp_path, monkeypatch):
    archive = tmp_path / "package.tgz"
    report = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["check", str(archive), "--report", str(report)])
    monkeypatch.setattr(checker, "validate_archive", lambda _: ({"a": b"bytes"}, "0.2.0"))

    def api(repository, path, payload=None):
        assert payload is None
        if "/actions/" in path:
            return {"workflow_runs": [{"event": "push", "head_sha": "old-commit", "html_url": "old-run"}]}
        return [status(fingerprint="another-package")]

    monkeypatch.setattr(checker, "api", api)
    with pytest.raises(SystemExit, match="No successful public package matrix"):
        checker.main()
    assert not report.exists()
