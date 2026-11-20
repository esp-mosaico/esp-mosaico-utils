"""Registry example acquisition preserves version, cache and SDK command boundaries."""

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from mosaico_cli import registry_examples as examples
from mosaico_cli.errors import EnvironmentError, SelectionError


@pytest.fixture
def registry(tmp_path, monkeypatch):
    workspace = SimpleNamespace(tool_root=tmp_path, run_dir=tmp_path / "runs")
    pin = {
        "schema_version": 1,
        "component": "espressif2022/raylib-lite-engine",
        "version": "0.1.1",
        "revision": "a" * 40,
        "archive_url": "https://example.invalid/source",
        "archive_sha256": "b" * 64,
    }
    (tmp_path / "raylib-toolchain.json").write_text(json.dumps(pin))
    calls = []
    state = SimpleNamespace(fail=False)
    sdk = SimpleNamespace(python=Path("/sdk/python"), idf_py=Path("/sdk/tools/idf.py"), values={"IDF_PATH": "/sdk"})

    class Context:
        log_path = tmp_path / "download.log"

        def __init__(self, *args):
            pass

        def status(self, message):
            self.log_path.write_text(message)

        def run(self, argv, *, cwd, env, timeout):
            calls.append((argv, cwd, env))
            if state.fail:
                return SimpleNamespace(returncode=1)
            assert argv == [
                sdk.python,
                sdk.idf_py,
                "create-project-from-example",
                "espressif2022/raylib-lite-engine=0.1.1:last_zone_extraction",
            ]
            assert env == sdk.values
            source = cwd / "last_zone_extraction"
            for name in examples.REQUIRED_FILES:
                p = source / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("# downloaded source\n")
            (source / "main/idf_component.yml").write_text(
                'dependencies:\n  espressif2022/raylib-lite-engine: "^0.1.1"\n'
            )
            return SimpleNamespace(returncode=0)

    monkeypatch.setattr("mosaico_cli.runtime.RunContext", Context)
    monkeypatch.setattr("mosaico_cli.runtime.resolve_idf_path", lambda *_: Path("/sdk"))
    monkeypatch.setattr(examples, "prepare_idf_environment", lambda *_: sdk)
    return workspace, calls, state


def test_download_uses_published_version_and_reuses_cache_without_sdk(registry, monkeypatch):
    workspace, calls, _ = registry
    project = examples.ensure_example(workspace, "last_zone_extraction")
    assert project == workspace.run_dir / "registry-examples/0.1.1/last_zone_extraction"
    assert len(calls) == 1
    assert calls[0][1] != workspace.run_dir  # No files created in the user's cwd.
    assert '"==0.1.1"' in (project / "main/idf_component.yml").read_text()
    monkeypatch.setattr(examples, "prepare_idf_environment", lambda *_: pytest.fail("cached example needs no SDK"))
    assert examples.ensure_example(workspace, "last_zone_extraction") == project
    assert len(calls) == 1


def test_download_failure_does_not_publish_or_leave_partial_project(registry):
    workspace, calls, state = registry
    state.fail = True
    with pytest.raises(EnvironmentError, match="download failed"):
        examples.ensure_example(workspace, "last_zone_extraction")
    assert len(calls) == 1
    assert not (workspace.run_dir / "registry-examples/0.1.1/last_zone_extraction").exists()
    assert not list(workspace.run_dir.rglob(".example-fetch-*"))


def test_existing_unverified_directory_is_preserved(registry):
    workspace, calls, _ = registry
    cache = workspace.run_dir / "registry-examples/0.1.1/last_zone_extraction"
    cache.mkdir(parents=True)
    (cache / "user-work").write_text("preserve")
    with pytest.raises(EnvironmentError, match="Incomplete Registry example cache"):
        examples.ensure_example(workspace, "last_zone_extraction")
    assert not calls
    assert (cache / "user-work").read_text() == "preserve"


def test_unknown_example_never_falls_back_to_source_repository(registry):
    workspace, calls, _ = registry
    with pytest.raises(SelectionError):
        examples.ensure_example(workspace, "../../unpublished_dev")
    assert not calls
