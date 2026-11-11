"""Only an Iris-owned S31 self-reset switches to ROM digital reset."""
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("single_core", [0, 1])
def test_s31_restart_tail(tmp_path, single_core):
    source = Path(__file__).resolve().parents[2] / "src/esp_iris_restart_s31.c"
    (tmp_path / "sdk.h").write_text("""
#pragma once
#define IRAM_ATTR
int esp_cpu_get_core_id(void);
void esp_cpu_reset(int core);
void esp_cpu_unstall(int core);
void esp_rom_software_reset_system(void);
""")
    for name in ("sdkconfig.h", "esp_attr.h", "esp_cpu.h", "esp_rom_sys.h"):
        (tmp_path / name).write_text('#include "sdk.h"\n')
    main = tmp_path / "main.c"
    main.write_text("""
#include <assert.h>
#include <setjmp.h>
#include <stdbool.h>
#include "sdk.h"
void esp_iris_s31_restart_cpu_reset(int core);
static int current, reset_core, unstalled, system_resets;
static bool iris_claimed;
static jmp_buf restarted;
int esp_cpu_get_core_id(void) { return current; }
bool iris_services_restart_claimed(void) { return iris_claimed; }
void esp_cpu_reset(int core) { reset_core = core; }
void esp_cpu_unstall(int core) { unstalled = core; }
void esp_rom_software_reset_system(void) {
    assert(unstalled == (CONFIG_ESP_SYSTEM_SINGLE_CORE_MODE ? -1 : (current ^ 1)));
    ++system_resets;
    longjmp(restarted, 1);
}
int main(void) {
    for (current = 0; current < 2; ++current) {
        reset_core = unstalled = -1;
        system_resets = 0;
        iris_claimed = false;
        esp_iris_s31_restart_cpu_reset(current);
        assert(reset_core == current && unstalled == -1 && !system_resets);
        reset_core = -1;
        iris_claimed = true;
        esp_iris_s31_restart_cpu_reset(current ^ 1);
        assert(reset_core == (current ^ 1) && unstalled == -1 && !system_resets);
        reset_core = -1;
        if (!setjmp(restarted)) esp_iris_s31_restart_cpu_reset(current);
        assert(reset_core == -1 && system_resets == 1);
    }
    return 0;
}
""")
    binary = tmp_path / "restart-test"
    subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-DCONFIG_ESP_SYSTEM_SINGLE_CORE_MODE=" + str(single_core),
                    "-I" + str(tmp_path), str(source), str(main), "-o", str(binary)],
                   check=True, capture_output=True, timeout=30)
    subprocess.run([str(binary)], check=True, capture_output=True, timeout=10)
