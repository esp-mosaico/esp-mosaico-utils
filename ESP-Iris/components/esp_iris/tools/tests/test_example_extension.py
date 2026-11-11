"""Downloaded examples must configure before dependencies have arrived."""
import importlib.util
import sys
from pathlib import Path

import pytest


def load_extension(path):
    spec = importlib.util.spec_from_file_location("example_extension", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_detached_example_waits_for_dependency_download(tmp_path):
    original = Path(__file__).parents[2] / "examples/minimal/idf_ext.py"
    project = tmp_path / "example"
    project.mkdir()
    shim = project / "idf_ext.py"
    shim.write_bytes(original.read_bytes())
    extension = load_extension(shim)
    actions = {"actions": {"build": {"callback": object()}}}
    assert extension.action_extensions(actions, str(project)) == {}
    assert "build" in actions["actions"]


@pytest.mark.parametrize("layout", ["managed_components/espressif__esp_iris", "components/esp_iris", "source"])
def test_example_loads_installed_extension(tmp_path, monkeypatch, layout):
    original = Path(__file__).parents[2] / "examples/minimal/idf_ext.py"
    if layout == "source":
        component = tmp_path / "esp_iris"
        project = component / "examples/minimal"
    else:
        project = tmp_path / "example"
        component = project / layout
    project.mkdir(parents=True)
    shim = project / "idf_ext.py"
    shim.write_bytes(original.read_bytes())
    tools = component / "tools"
    package = tools / "iris_usb_flash"
    package.mkdir(parents=True)
    package.joinpath("__init__.py").write_text(
        "def action_extensions(base_actions, project_path):\n"
        "    base_actions['loaded'] = project_path\n"
        "    return {'global_action_callbacks': []}\n"
    )
    monkeypatch.delitem(sys.modules, "iris_usb_flash", raising=False)
    monkeypatch.setattr(sys, "path", sys.path[:])
    try:
        actions = {}
        result = load_extension(shim).action_extensions(actions, str(project))
        assert actions["loaded"] == str(project)
        assert result == {"global_action_callbacks": []}
    finally:
        sys.modules.pop("iris_usb_flash", None)
