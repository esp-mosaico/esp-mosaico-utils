"""Exercise the real Recovery pages with native LVGL and fake device services."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
RECOVERY = ROOT / "firmware/recovery"
FIXTURE = ROOT / "tests/host_ui"


@pytest.mark.skipif(sys.platform != "linux", reason="Native Recovery UI fixture uses Linux")
def test_recovery_ui_layout_and_wifi_continuation(tmp_path):
    lvgl = Path(os.environ.get("LVGL_COMPONENT_DIR", str(RECOVERY / "managed_components/lvgl__lvgl")))
    assert (lvgl / "CMakeLists.txt").is_file(), "Build Recovery first or set LVGL_COMPONENT_DIR"
    for name in ("sdkconfig.h", "esp_err.h", "esp_check.h", "esp_log.h", "esp_wifi.h",
                 "bsp/esp_mosaico.h", "freertos/FreeRTOS.h", "freertos/task.h"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#include "sdk.h"\n')
    (tmp_path / "lv_conf.h").write_text("\n".join([
        "#pragma once", "#define LV_CONF_H", "#define LV_COLOR_DEPTH 16", "#define LV_DPI_DEF 60",
        "#define LV_USE_STDLIB_MALLOC LV_STDLIB_CLIB", "#define LV_USE_SNAPSHOT 1",
        *["#define LV_FONT_MONTSERRAT_{} 1".format(size) for size in (12, 14, 22, 32, 48)],
        "",
    ]))
    (tmp_path / "CMakeLists.txt").write_text(f'''
cmake_minimum_required(VERSION 3.16)
project(recovery_ui_test C CXX)
set(CONFIG_LV_BUILD_DEMOS OFF CACHE BOOL "" FORCE)
set(CONFIG_LV_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(CONFIG_LV_USE_THORVG_INTERNAL OFF CACHE BOOL "" FORCE)
set(LV_BUILD_CONF_PATH "{tmp_path / 'lv_conf.h'}" CACHE PATH "" FORCE)
add_subdirectory("{lvgl}" lvgl)
add_executable(recovery-ui "{FIXTURE / 'main.c'}")
target_compile_definitions(recovery-ui PRIVATE UI_SOURCE="{RECOVERY / 'main/factory_ui.c'}")
target_compile_definitions(recovery-ui PRIVATE UI_INPUT_SOURCE="{RECOVERY / 'main/factory_ui_input.c'}")
target_compile_options(recovery-ui PRIVATE -Werror=implicit-function-declaration -UNDEBUG)
target_include_directories(recovery-ui PRIVATE "{tmp_path}" "{FIXTURE}"
    "{RECOVERY / 'main'}" "{RECOVERY / 'components/iris_bridge/include'}"
    "{ROOT.parent / 'ESP-Iris/components/esp_iris/include'}")
target_link_libraries(recovery-ui PRIVATE lvgl m)
''')
    build = tmp_path / "build"
    commands = [
        ["cmake", "-S", str(tmp_path), "-B", str(build), "-G", "Ninja"],
        ["cmake", "--build", str(build), "--parallel", "4"],
        [str(build / "recovery-ui")],
    ]
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
        assert result.returncode == 0, result.stdout + result.stderr
