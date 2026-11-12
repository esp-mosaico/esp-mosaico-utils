"""Pin verification, safe cache publication and Registry-default scaffolding."""

import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tarfile
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from mosaico_cli import raylib_toolchain as tools
from mosaico_cli.errors import EnvironmentError


@pytest.fixture
def source(tmp_path, monkeypatch):
    archive = tmp_path / "source.tar.gz"
    pin = {
        "schema_version": 1,
        "revision": "a" * 40,
        "component": "espressif2022/raylib-lite-engine",
        "version": "0.1.0",
        "archive_url": "https://example.invalid/source.tar.gz",
    }

    def pack(extra=None):
        with tarfile.open(archive, "w:gz") as output:
            for name in tools.REQUIRED_FILES:
                item = tarfile.TarInfo("raylib-lite-engine-" + pin["revision"] + "/" + name)
                content = b"# fixture\n"
                item.size = len(content)
                output.addfile(item, io.BytesIO(content))
            if extra:
                output.addfile(extra, io.BytesIO(b"x") if extra.isfile() else None)
        pin["archive_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
        (tmp_path / "raylib-toolchain.json").write_text(json.dumps(pin))

    pack()
    monkeypatch.setattr(tools, "_download", lambda url, destination: shutil.copyfile(archive, destination))
    workspace = SimpleNamespace(tool_root=tmp_path, run_dir=tmp_path / "runs", raylib_path=None)
    return workspace, pin, pack


def test_verified_cache_is_reused_offline(source, monkeypatch):
    workspace, pin, _ = source
    result = tools.ensure_toolchain(workspace)
    assert result == tools.cache_path(workspace.tool_root, workspace.run_dir)
    assert json.loads((result / ".mosaico-toolchain.json").read_text()) == pin
    monkeypatch.setattr(tools, "_download", lambda *_: pytest.fail("must reuse cache offline"))
    assert tools.ensure_toolchain(workspace) == result


def test_explicit_developer_source_is_not_replaced_or_downloaded(source, monkeypatch):
    workspace, _, _ = source
    workspace.raylib_path = workspace.tool_root / "developer checkout"
    monkeypatch.setattr(tools, "_download", lambda *_: pytest.fail("must respect explicit source"))
    assert tools.ensure_toolchain(workspace) == workspace.raylib_path


def test_hash_mismatch_never_publishes_cache(source):
    workspace, pin, _ = source
    pin["archive_sha256"] = "0" * 64
    (workspace.tool_root / "raylib-toolchain.json").write_text(json.dumps(pin))
    with pytest.raises(EnvironmentError, match="SHA-256 mismatch"):
        tools.ensure_toolchain(workspace)
    assert not tools.cache_path(workspace.tool_root, workspace.run_dir).exists()
    assert not list(workspace.run_dir.rglob(".raylib-fetch-*"))


def test_archive_cannot_write_outside_cache(source):
    workspace, pin, pack = source
    extra = tarfile.TarInfo("raylib-lite-engine-" + pin["revision"] + "/../../escaped")
    extra.size = 1
    pack(extra)
    with pytest.raises(EnvironmentError, match="Unsafe Raylib archive path"):
        tools.ensure_toolchain(workspace)
    assert not (workspace.tool_root / "escaped").exists()
    assert not tools.cache_path(workspace.tool_root, workspace.run_dir).exists()


def test_archive_links_are_not_followed(source):
    workspace, pin, pack = source
    extra = tarfile.TarInfo("raylib-lite-engine-" + pin["revision"] + "/external-link")
    extra.type = tarfile.SYMTYPE
    extra.linkname = "/tmp/outside-cache"
    pack(extra)
    result = tools.ensure_toolchain(workspace)
    assert not (result / "external-link").is_symlink()


def test_incomplete_cache_is_preserved_for_inspection(source):
    workspace, _, _ = source
    cache = tools.cache_path(workspace.tool_root, workspace.run_dir)
    cache.mkdir(parents=True)
    (cache / "user-work").write_text("preserve me")
    with pytest.raises(EnvironmentError, match="Incomplete Raylib"):
        tools.ensure_toolchain(workspace)
    assert (cache / "user-work").read_text() == "preserve me"


def test_concurrent_publication_accepts_only_the_same_verified_pin(source, monkeypatch):
    workspace, _, _ = source
    cache = tools.cache_path(workspace.tool_root, workspace.run_dir)

    def publish_other(prepared, destination):
        assert destination == cache
        shutil.copytree(prepared, destination)
        raise FileExistsError("another process won")

    monkeypatch.setattr(Path, "rename", publish_other)
    assert tools.ensure_toolchain(workspace) == cache


def test_new_example_uses_registry_without_touching_other_overrides(source):
    workspace, _, _ = source
    manifest = workspace.tool_root / "idf_component.yml"
    manifest.write_text("""dependencies:
  idf: ">=6.2"
  espressif2022/raylib-lite-engine:
    version: "^0.1.0"
    override_path: /developer/engine
  example/other:
    version: "^1.0"
    override_path: /developer/other
""")
    tools.use_registry_engine(manifest, workspace.tool_root)
    import yaml

    dependencies = yaml.safe_load(manifest.read_text())["dependencies"]
    assert dependencies["espressif2022/raylib-lite-engine"] == "==0.1.0"
    assert dependencies["example/other"]["override_path"] == "/developer/other"
