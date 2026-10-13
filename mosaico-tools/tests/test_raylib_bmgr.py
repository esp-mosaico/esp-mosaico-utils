"""Iris wrappers own their BMGR output independently of native Game projects."""
from pathlib import Path
from types import SimpleNamespace
import sys
from unittest.mock import patch
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from mosaico_cli.app_commands import _prepare_iris_board
from mosaico_cli.errors import BuildError, EnvironmentError

@pytest.mark.parametrize('generated_board', ['esp_mosaico', 'esp32_s3_box_3'])
def test_wrapper_board_is_generated_and_verified(tmp_path, generated_board):
    engine = tmp_path / 'engine'
    profile = engine / 'examples/boards/esp-mosaico/bmgr/esp_mosaico'
    profile.mkdir(parents=True)
    (profile / 'board_info.yaml').write_text('board: esp_mosaico\n')
    project = tmp_path / 'runs/my-game/project'
    project.mkdir(parents=True)
    native = tmp_path / 'user-game/components/gen_bmgr_codes'
    native.mkdir(parents=True)
    (native / 'gen_board_metadata.yaml').write_text('board: esp32_s3_box_3\n')
    commands = []
    def resolve_plugin(context, **kwargs):
        plugin = kwargs['project'] / 'managed_components/espressif__esp_board_manager'
        plugin.mkdir(parents=True)
        (plugin / 'idf_ext.py').write_text('')
    def generate(argv, **kwargs):
        commands.append((argv, kwargs))
        output = project / 'components/gen_bmgr_codes'
        output.mkdir(parents=True)
        (output / 'gen_board_metadata.yaml').write_text('board: '+generated_board+'\n')
        return SimpleNamespace(returncode=0)
    context = SimpleNamespace(workspace=SimpleNamespace(), run=generate, log_path=tmp_path/'log')
    with patch('mosaico_cli.runtime.resolve_idf_path', return_value=tmp_path/'idf'), patch(
        'mosaico_cli.runtime.run_idf_target', side_effect=resolve_plugin), patch(
        'mosaico_cli.runtime.idf_target_command', return_value={'argv':['idf.py','bmgr'], 'env':{}}):
        if generated_board == 'esp_mosaico':
            _prepare_iris_board(context, project, engine)
        else:
            with pytest.raises(BuildError, match='required Mosaico'):
                _prepare_iris_board(context, project, engine)
    assert commands[0][0][-4:] == ['-c', str(profile.parent), '-b', 'esp_mosaico']
    assert commands[0][1]['cwd'] == project
    assert 'IDF_EXTRA_ACTIONS_PATH' in commands[0][1]['env']
    assert (native/'gen_board_metadata.yaml').read_text() == 'board: esp32_s3_box_3\n'

def test_missing_profile_fails_before_idf_execution(tmp_path):
    context = SimpleNamespace(workspace=SimpleNamespace())
    with patch('mosaico_cli.runtime.run_idf_target') as run:
        with pytest.raises(EnvironmentError, match='BMGR profile'):
            _prepare_iris_board(context, tmp_path/'wrapper', tmp_path/'engine')
        run.assert_not_called()
