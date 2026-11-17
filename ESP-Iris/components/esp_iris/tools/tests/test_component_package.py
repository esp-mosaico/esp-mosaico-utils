"""Exercise actual package contents, including rejected incomplete releases."""
import importlib.util
import io
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

pytest.importorskip("idf_component_manager", reason="The package CI job installs the release packer")

IRIS = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("package_check", IRIS / "tools/check_component_package.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


@pytest.fixture(scope="module")
def archive(tmp_path_factory):
    if os.environ.get("IRIS_PACKAGE_ARCHIVE"):
        return Path(os.environ["IRIS_PACKAGE_ARCHIVE"])
    destination = tmp_path_factory.mktemp("iris-package")
    subprocess.run([
        sys.executable, "-c", "from idf_component_manager.cli import safe_cli; safe_cli()",
        "component", "pack", "--name", "esp_iris", "--project-dir", str(IRIS / "components/esp_iris"),
        "--dest-dir", str(destination),
    ], check=True, capture_output=True, text=True)
    archives = list(destination.glob("*.tgz"))
    assert len(archives) == 1
    return archives[0]


def test_package_runs_without_the_checkout(archive, tmp_path):
    files, version = checker.validate_archive(archive)
    project, component = checker.prepare_consumer(files, tmp_path)
    assert project.parent == tmp_path
    checker.check_host(component, tmp_path, version)


@pytest.mark.parametrize("fault", ["missing_frontend", "missing_asset", "build_log", "wrong_namespace",
                                  "wrong_version", "broken_link", "frontend_test", "missing_changelog", "missing_launcher"])
def test_package_rejects_incomplete_or_contaminated_release(archive, tmp_path, fault):
    files, _ = checker.validate_archive(archive)
    if fault == "missing_frontend":
        del files["tools/frontend/dist/index.html"]
    elif fault == "missing_asset":
        asset = next(name for name in files if name.startswith("tools/frontend/dist/assets/") and name.endswith(".js"))
        del files[asset]
    elif fault == "build_log":
        files["examples/minimal/.codex-runs/build/raw.log"] = b"local build evidence"
    elif fault == "wrong_namespace":
        name = "examples/minimal/main/idf_component.yml"
        files[name] = files[name].replace(b"espressif/esp_iris", b"unpublished/esp_iris")
    elif fault == "broken_link":
        files["README.md"] += b'\n[Missing guide](../private/guide.md)\n'
    elif fault == "frontend_test":
        files["tools/frontend/src/views/workbench.test.tsx"] = b"test-only implementation"
    elif fault == "missing_changelog":
        files["CHANGELOG.md"] = b"## Unreleased\n"
    elif fault == "missing_launcher":
        del files["examples/rpc_jobs/esp_iris.py"]
    else:
        files["tools/iris_gateway/__init__.py"] = b'__version__ = "99.0.0"\n'
    broken = tmp_path / "broken.tgz"
    with tarfile.open(broken, "w:gz") as stream:
        for name, data in files.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            stream.addfile(entry, io.BytesIO(data))
    with pytest.raises(ValueError):
        checker.validate_archive(broken)


def test_package_rejects_mismatched_release_tag(archive):
    with pytest.raises(ValueError, match="tag"):
        checker.validate_archive(archive, "esp-iris-v99.0.0")


@pytest.mark.parametrize("fault", [None, "missing_file", "changed_file", "wrong_version", "wrong_dependency"])
def test_registry_installation_matches_release_archive(archive, tmp_path, fault):
    files, version = checker.validate_archive(archive)
    _, component = checker.prepare_consumer(files, tmp_path)
    if fault == "missing_file":
        (component / "tools/frontend/dist/index.html").unlink()
    elif fault == "changed_file":
        (component / "tools/iris_gateway/__init__.py").write_text('__version__ = "changed"\n')
    elif fault == "wrong_version":
        (component / "idf_component.yml").write_text('version: "99.0.0"\n')
    elif fault == "wrong_dependency":
        manifest = component / "idf_component.yml"
        yaml = checker.YAML()
        data = yaml.load(manifest)
        data["dependencies"]["idf"] = ">=99.0"
        with manifest.open("w") as stream:
            yaml.dump(data, stream)
    if fault:
        with pytest.raises(ValueError):
            checker.check_installed_component(files, component, version)
    else:
        checker.check_installed_component(files, component, version)


def test_registry_verification_preserves_existing_project(tmp_path):
    project = tmp_path / "minimal"
    project.mkdir()
    marker = project / "keep.txt"
    marker.write_text("existing project")
    with pytest.raises(ValueError, match="new work directory"):
        checker.prepare_registry_consumer(tmp_path, "0.2.0", "https://components-staging.espressif.com")
    assert marker.read_text() == "existing project"


@pytest.mark.parametrize("local_key", [None, "override_path", "path", "git"])
def test_downloaded_example_uses_registry_dependency(tmp_path, monkeypatch, local_key):
    registry = "https://components-staging.espressif.com"

    def download(*args, **kwargs):
        manifest = tmp_path / "minimal/main/idf_component.yml"
        manifest.parent.mkdir(parents=True)
        local = f'    {local_key}: "../local"\n' if local_key else ""
        manifest.write_text('dependencies:\n  espressif/esp_iris:\n    version: "*"\n' + local)

    monkeypatch.setattr(checker.subprocess, "run", download)
    if local_key:
        with pytest.raises(ValueError, match="local or Git"):
            checker.prepare_registry_consumer(tmp_path, "0.2.0", registry)
    else:
        project, component = checker.prepare_registry_consumer(tmp_path, "0.2.0", registry)
        data = checker.YAML(typ="safe").load(project / "main/idf_component.yml")
        assert data["dependencies"]["espressif/esp_iris"] == {"version": "=0.2.0", "registry_url": registry}
        assert not component.exists()


@pytest.mark.parametrize("example", ["rpc_jobs", "tcp_wifi", "ota"])
def test_selected_example_runs_its_packaged_launcher(archive, tmp_path, example):
    files, _ = checker.validate_archive(archive)
    project, _ = checker.prepare_consumer(files, tmp_path, example)
    result = subprocess.run([sys.executable, "-I", str(project / "esp_iris.py"), "--help"],
                            cwd=tmp_path, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "setup|doctor|web|ctl" in result.stdout


@pytest.mark.parametrize("example", ["unknown", "../minimal", "/minimal"])
def test_invalid_example_is_rejected_before_writing(archive, tmp_path, example):
    files, _ = checker.validate_archive(archive)
    with pytest.raises(ValueError, match="Unknown package example"):
        checker.prepare_consumer(files, tmp_path, example)
    assert not list(tmp_path.iterdir())


def test_content_fingerprint_tracks_names_and_bytes():
    original = {"a": b"first", "b": b"second"}
    assert checker.package_fingerprint(original) == checker.package_fingerprint(dict(reversed(list(original.items()))))
    assert checker.package_fingerprint(original) != checker.package_fingerprint({**original, "b": b"changed"})
    assert checker.package_fingerprint(original) != checker.package_fingerprint({"a": b"first", "c": b"second"})
