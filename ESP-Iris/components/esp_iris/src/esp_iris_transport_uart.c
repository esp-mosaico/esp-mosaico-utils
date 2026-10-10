#include "esp_iris_internal.h"

#include <errno.h>

#include "driver/uart.h"
#include "driver/uart_vfs.h"

_Static_assert(CONFIG_ESP_IRIS_UART_NUM < UART_NUM_MAX, "invalid Iris UART port");

#define IRIS_UART_PORT ((uart_port_t)CONFIG_ESP_IRIS_UART_NUM)

static esp_err_t uart_start(iris_runtime_t *runtime, iris_transport_state_t *state)
{
    if (runtime == NULL || state == NULL) return ESP_ERR_INVALID_ARG;
    if (state->driver_started) return ESP_OK;
#if CONFIG_ESP_IRIS_CONSOLE_EXTERNAL_INPUT
    if (!uart_is_driver_installed(IRIS_UART_PORT)) return ESP_ERR_INVALID_STATE;
#endif
    state->driver_owned = !uart_is_driver_installed(IRIS_UART_PORT);
    if (state->driver_owned) {
        const uart_config_t config = {
#if CONFIG_ESP_CONSOLE_UART && CONFIG_ESP_IRIS_UART_NUM == CONFIG_ESP_CONSOLE_UART_NUM
            .baud_rate = CONFIG_ESP_CONSOLE_UART_BAUDRATE,
#else
            .baud_rate = CONFIG_ESP_IRIS_UART_BAUDRATE,
#endif
            .data_bits = UART_DATA_8_BITS, .parity = UART_PARITY_DISABLE,
            .stop_bits = UART_STOP_BITS_1, .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
            .source_clk = UART_SCLK_DEFAULT,
        };
        esp_err_t err = uart_param_config(IRIS_UART_PORT, &config);
        if (err == ESP_OK) err = uart_set_pin(IRIS_UART_PORT,
            CONFIG_ESP_IRIS_UART_TX_GPIO, CONFIG_ESP_IRIS_UART_RX_GPIO,
            UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
        if (err == ESP_OK) err = uart_driver_install(IRIS_UART_PORT,
            IRIS_CONSOLE_RECORD_BYTES * 2U, IRIS_CONSOLE_RECORD_BYTES * 2U,
            0, NULL, 0);
        if (err != ESP_OK) return err;
    }
#if CONFIG_ESP_IRIS_CONSOLE_EXTERNAL_INPUT
    iris_console_input_enable(true);
#else
    uart_vfs_dev_use_driver(IRIS_UART_PORT);
#endif
    state->driver_started = true;
    state->link_up = false;
    state->reported_link_up = false;
    return ESP_OK;
}

static void uart_stop(iris_runtime_t *runtime, iris_transport_state_t *state)
{
    (void)runtime;
    if (!state->driver_started) return;
#if CONFIG_ESP_IRIS_CONSOLE_EXTERNAL_INPUT
    iris_console_input_enable(false);
#endif
    if (state->driver_owned) {
        uart_vfs_dev_use_nonblocking(IRIS_UART_PORT);
        if (uart_driver_delete(IRIS_UART_PORT) != ESP_OK) return;
    }
    state->driver_started = false;
    state->link_up = false;
    state->reported_link_up = false;
}

static void uart_disconnect(iris_runtime_t *runtime, iris_transport_state_t *state)
{
    (void)runtime;
    state->link_up = false;
    state->reported_link_up = false;
}

static iris_link_event_t uart_poll(iris_runtime_t *runtime, iris_transport_state_t *state)
{
    (void)runtime;
    size_t available = 0;
    if (!state->driver_started) return IRIS_LINK_EVENT_NONE;
#if CONFIG_ESP_IRIS_CONSOLE_EXTERNAL_INPUT
    available = iris_console_input_available() ? 1 : 0;
#else
    if (uart_get_buffered_data_len(IRIS_UART_PORT, &available) != ESP_OK)
        return IRIS_LINK_EVENT_NONE;
#endif
    if (!state->link_up && available > 0) state->link_up = true;
    if (state->link_up == state->reported_link_up) return IRIS_LINK_EVENT_NONE;
    state->reported_link_up = state->link_up;
    return state->link_up ? IRIS_LINK_EVENT_CONNECTED : IRIS_LINK_EVENT_DISCONNECTED;
}

static int uart_read(iris_runtime_t *runtime, iris_transport_state_t *state,
                     uint8_t *buffer, size_t capacity)
{
    (void)runtime;
    if (!state->link_up) return -ENOTCONN;
#if CONFIG_ESP_IRIS_CONSOLE_EXTERNAL_INPUT
    return iris_console_input_read(buffer, capacity);
#else
    return uart_read_bytes(IRIS_UART_PORT, buffer, capacity, 0);
#endif
}

static int uart_write(iris_runtime_t *runtime, iris_transport_state_t *state,
                      const uint8_t *buffer, size_t length)
{
    (void)runtime;
    if (!state->link_up) return -ENOTCONN;
    /* Preserve queued native output order; never bypass the driver TX ring. */
    return uart_write_bytes(IRIS_UART_PORT, buffer, length);
}

const iris_transport_ops_t g_iris_uart_transport_ops = {
    .kind = ESP_IRIS_TRANSPORT_KIND_UART, .name = "uart",
    .start = uart_start, .stop = uart_stop, .disconnect = uart_disconnect,
    .poll = uart_poll, .read = uart_read, .write = uart_write,
};
