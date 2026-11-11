"""An unreviewed candidate must always be explicitly located before any side effect."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from mosaico_cli import cli, commands
from mosaico_cli.errors import SelectionError
from mosaico_cli.recovery import source_project
from test_cli import create_source_project


@pytest.mark.parametrize("command,source_flag,path_flag", [
    (["recover"], "--source", "--source-path"),
    (["iris", "app-update"], "--recovery-source", "--recovery-source-path"),
])
def test_parser_requires_path_for_current_and_rejects_it_for_reviewed(command, source_flag, path_flag):
    parser = cli.build_parser()
    with pytest.raises(SystemExit) as missing:
        parser.parse_args(command + [source_flag, "current"])
    assert missing.value.code == 2
    with pytest.raises(SystemExit) as incompatible:
        parser.parse_args(command + [path_flag, "candidate"])
    assert incompatible.value.code == 2
    value = parser.parse_args(command + [source_flag, "current", path_flag, "candidate"])
    assert getattr(value, path_flag[2:].replace("-", "_")) == "candidate"


@pytest.mark.parametrize("function,prefix", [(commands.recover, ""), (commands.install, "recovery_")])
@pytest.mark.parametrize("path", [None, "", "/no-such-vibe-source"])
def test_bad_source_path_fails_before_gateway_or_build(monkeypatch, function, prefix, path):
    gateway, build = Mock(), Mock()
    monkeypatch.setattr(commands, "ensure_gateway", gateway)
    monkeypatch.setattr(commands, "run_idf_target", build)
    monkeypatch.setattr(commands, "build_application", build)
    args = SimpleNamespace(**{prefix + "source": "current", prefix + "source_path": path})
    with pytest.raises(SelectionError):
        function(args, Mock())
    gateway.assert_not_called()
    build.assert_not_called()


def test_source_path_is_relative_to_caller_not_workspace(tmp_path, monkeypatch):
    project = create_source_project(tmp_path / "candidate with spaces")
    monkeypatch.chdir(tmp_path)
    assert source_project("current", "candidate with spaces") == project.resolve()
    assert source_project("reviewed", None) is None
    with pytest.raises(SelectionError):
        source_project("reviewed", str(project))


def test_explicit_private_source_cannot_be_selected_as_an_application(tmp_path):
    from mosaico_cli.project import resolve_project
    from test_cli import workspace_for
    project = create_source_project(tmp_path / "candidate")
    (project / "CMakeLists.txt").write_text("project(vibe-mode)\n")
    (project / "sdkconfig.recovery.defaults").write_text("CONFIG_FACTORY_RECOVERY_FIRMWARE=y\n")
    with pytest.raises(SelectionError, match="cannot be installed"):
        resolve_project(workspace_for(tmp_path), str(project), tmp_path)
