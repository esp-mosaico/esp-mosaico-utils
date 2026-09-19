"""Validate effective build config, including reuse of an old build."""
import json
import sys
from unittest.mock import Mock, patch
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "mosaico-tools/tools"))

from mosaico_cli.errors import BuildError, EnvironmentError
from mosaico_cli.product_contract import validate_application_config
from mosaico_cli.gateway import run_system_update_bundle

CONFIG = {"IDF_TARGET": "esp32s31", "ESP_IRIS_FIRMWARE_ROLE": 1,
          "ESP_IRIS_PRODUCT_CONTRACT": "esp-mosaico/v1", "ESP_IRIS_BOARD_ID": "esp-mosaico",
          "ESP_IRIS_LAYOUT_ID": "mosaico-retained-recovery-2m-v1", "ESP_IRIS_RECOVERY_ABI": 1,
          "ESP_IRIS_OTA": False, "ESP_IRIS_OTA_DEFAULT_VIA_RECOVERY": True,
          "ESP_IRIS_SYSTEM_INVENTORY": True}


@pytest.mark.parametrize("key", list(CONFIG))
def test_effective_config_rejects_omissions_even_if_defaults_exist(tmp_path, key):
    (tmp_path / "config").mkdir()
    config = dict(CONFIG)
    config.pop(key)
    (tmp_path / "config/sdkconfig.json").write_text(json.dumps(config))
    (tmp_path / "sdkconfig.defaults").write_text("CONFIG_ESP_IRIS_FIRMWARE_ROLE=1\n")
    with pytest.raises(BuildError) as error:
        validate_application_config(tmp_path)
    assert key in error.value.details["mismatches"]


@pytest.mark.parametrize("value", [0, 2, True, "1"])
def test_effective_config_rejects_wrong_role(tmp_path, value):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/sdkconfig.json").write_text(json.dumps({**CONFIG, "ESP_IRIS_FIRMWARE_ROLE": value}))
    with pytest.raises(BuildError):
        validate_application_config(tmp_path)


def test_effective_config_accepts_normal_application(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/sdkconfig.json").write_text(json.dumps(CONFIG))
    validate_application_config(tmp_path)


def test_system_update_requires_contract_acceptance_before_submission():
    context = Mock()
    with patch("mosaico_cli.gateway.gateway_json", return_value={"capabilities": []}):
        with pytest.raises(EnvironmentError, match="final firmware contract"):
            run_system_update_bundle(context, Mock(), device_id="d", bundle=Path("a.irisfw"), timeout=10)
    context.run.assert_not_called()


def test_bundle_plan_uses_public_inspection_before_writing():
    from mosaico_cli.bundle_plan import inspect_bundle_plan
    plan = {"components": [{"file": "game_assets.bin", "kind": "data", "target_offset": 0xf00000,
                             "size": 512, "sha256": "ab" * 32}]}
    context = Mock()
    context.run.return_value = Mock(returncode=0, stdout=json.dumps(plan))
    with patch("mosaico_cli.bundle_plan.ensure_iris_tools", return_value=(Path("python"), Path("iris"))):
        assert inspect_bundle_plan(context, Path("app.irisfw")) == plan
    assert context.run.call_args.args[0] == ["python", "iris", "bundle", "--json", "inspect", "app.irisfw"]
    assert "0xf00000" in context.status.call_args.args[0]
