import shutil
import subprocess
from pathlib import Path

import pytest


def test_product_console_queue_bounds_registration_and_lifetime(tmp_path):
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("C compiler required")
    component = Path(__file__).resolve().parents[2]
    host = Path(__file__).parent / "runtime_host"
    (tmp_path / "esp_console.h").write_text('''
#include "esp_err.h"
typedef struct {const char *command, *help, *hint; int (*func)(int, char **);} esp_console_cmd_t;
static esp_console_cmd_t registered;
static esp_err_t esp_console_cmd_register(const esp_console_cmd_t *cmd) {registered = *cmd; return ESP_OK;}
''')
    source = tmp_path / "console.c"
    source.write_text('''
#include <assert.h>
#include "esp_iris_console.c"
int main(void) {
    uint8_t out[ESP_IRIS_CONSOLE_LINE_BYTES];
    assert(esp_iris_console_submit("iris status", 11) == ESP_ERR_INVALID_STATE);
    iris_console_input_enable(true);
    assert(esp_iris_console_register_commands() == ESP_OK);
    assert(strcmp(registered.command, "iris") == 0);
    assert(esp_iris_console_submit("other", 5) == ESP_ERR_INVALID_ARG);
    assert(esp_iris_console_submit("iris x\\n", 7) == ESP_ERR_INVALID_ARG);
    assert(esp_iris_console_submit("iris status", 11) == ESP_OK);
    assert(esp_iris_console_submit("iris help", 9) == ESP_ERR_TIMEOUT);
    assert(iris_console_input_read(out, 4) == 4 && memcmp(out, "iris", 4) == 0);
    assert(esp_iris_console_submit("iris help", 9) == ESP_ERR_TIMEOUT);
    assert(iris_console_input_read(out, sizeof(out)) == 8 && memcmp(out, " status\\n", 8) == 0);
    assert(!iris_console_input_available());
    char *args[] = {"iris", "hello"};
    assert(registered.func(2, args) == ESP_OK);
    assert(iris_console_input_read(out, sizeof(out)) == 11 && memcmp(out, "iris hello\\n", 11) == 0);
    memset(out, 'x', sizeof(out)); memcpy(out, "iris ", 5);
    assert(esp_iris_console_submit((char *)out, sizeof(out)) == ESP_ERR_INVALID_ARG);
    assert(esp_iris_console_submit((char *)out, sizeof(out)-1) == ESP_OK);
    iris_console_input_enable(false);
    assert(!iris_console_input_available());
    assert(registered.func(2, args) == ESP_ERR_INVALID_STATE);
    iris_console_input_enable(true);
    assert(!iris_console_input_available());
    return 0;
}
''')
    output = tmp_path / "console"
    subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-DCONFIG_ESP_IRIS_ENABLE=1", "-DCONFIG_ESP_IRIS_CONSOLE_EXTERNAL_INPUT=1",
                    "-I", str(tmp_path), "-I", str(host), "-I", str(component / "include"),
                    "-I", str(component / "src"), str(source), "-o", str(output)],
                   check=True, capture_output=True, text=True)
    subprocess.run([str(output)], check=True, capture_output=True, text=True)
