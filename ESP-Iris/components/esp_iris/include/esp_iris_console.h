#pragma once

#include <stddef.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Configure the product REPL's max_cmdline_length to at least this value. */
#define ESP_IRIS_CONSOLE_LINE_BYTES 5476U

/* CONFIG_ESP_IRIS_CONSOLE_EXTERNAL_INPUT: register after esp_console_init(),
 * or after esp_console_new_repl_*(). The product remains the sole stdin reader
 * and owns the driver/REPL lifetime. Iris must stop before that driver stops.
 * Size the product RX driver queue to at least two complete line buffers;
 * small interactive driver defaults can drop a machine record burst.
 * The registered callback waits at most one second for queue admission, yielding
 * to the worker so bursts of API records and human commands do not lose lines.
 * This only registers the "iris" namespace; existing commands remain intact. */
esp_err_t esp_iris_console_register_commands(void);

/* Optional custom console integration. Submit a complete "iris ..." line,
 * without CR/LF, from the product's single input owner. Copied synchronously;
 * ESP_ERR_TIMEOUT means the bounded one-command queue is occupied. Responses
 * are asynchronous on the configured UART/Serial-JTAG console. */
esp_err_t esp_iris_console_submit(const char *line, size_t length);

#ifdef __cplusplus
}
#endif
