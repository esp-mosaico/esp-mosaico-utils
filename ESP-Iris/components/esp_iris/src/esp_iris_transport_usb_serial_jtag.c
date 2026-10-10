#include "esp_iris_internal.h"

#include <errno.h>

#include "driver/usb_serial_jtag.h"
#include "driver/usb_serial_jtag_vfs.h"
#include "esp_ipc.h"
#include "freertos/FreeRTOS.h"

/* IDF builds the VFS adapter only with VFS I/O and its native USJ console.
 * The Iris transport can also own a driver without that stdio adapter. */
#define IRIS_USB_SERIAL_JTAG_WRITE_CHUNK 256U

typedef struct {
    esp_err_t result;
} iris_usb_serial_jtag_uninstall_result_t;

static void uninstall_driver(void *argument)
{
    iris_usb_serial_jtag_uninstall_result_t *result = argument;
    result->result = usb_serial_jtag_driver_uninstall();
}

static esp_err_t usb_serial_jtag_start(iris_runtime_t *runtime,
                                       iris_transport_state_t *state)
{
    if (runtime == NULL || state == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    if (state->driver_started) {
        return ESP_OK;
    }
#if CONFIG_ESP_IRIS_CONSOLE_EXTERNAL_INPUT
    if (!usb_serial_jtag_is_driver_installed()) return ESP_ERR_INVALID_STATE;
#endif
    state->driver_owned = !usb_serial_jtag_is_driver_installed();

    usb_serial_jtag_driver_config_t config = {
        .tx_buffer_size = CONFIG_ESP_IRIS_USB_SERIAL_JTAG_TX_BUFFER_BYTES,
        .rx_buffer_size = CONFIG_ESP_IRIS_USB_SERIAL_JTAG_RX_BUFFER_BYTES,
        .intr_priority = 0,
    };
    esp_err_t err = state->driver_owned ? usb_serial_jtag_driver_install(&config) : ESP_OK;
    if (err != ESP_OK) {
        return err;
    }
#if CONFIG_ESP_IRIS_CONSOLE_EXTERNAL_INPUT
    iris_console_input_enable(true);
#elif CONFIG_VFS_SUPPORT_IO && CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG_ENABLED
    usb_serial_jtag_vfs_use_driver();
#endif

    state->usb_serial_jtag_install_core = xPortGetCoreID();
    state->driver_started = true;
    state->link_up = false;
    state->reported_link_up = false;
    return ESP_OK;
}

static void usb_serial_jtag_stop(iris_runtime_t *runtime,
                                 iris_transport_state_t *state)
{
    if (runtime == NULL || state == NULL || !state->driver_started) {
        return;
    }

#if CONFIG_ESP_IRIS_CONSOLE_EXTERNAL_INPUT
    iris_console_input_enable(false);
#endif
    iris_usb_serial_jtag_uninstall_result_t result = {
        .result = ESP_FAIL,
    };
    if (!state->driver_owned) {
        result.result = ESP_OK;
    } else if (xPortGetCoreID() == state->usb_serial_jtag_install_core) {
#if CONFIG_VFS_SUPPORT_IO && CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG_ENABLED
        usb_serial_jtag_vfs_use_nonblocking();
#endif
        uninstall_driver(&result);
    } else {
#if CONFIG_ESP_IPC_ENABLE
#if CONFIG_VFS_SUPPORT_IO && CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG_ENABLED
        usb_serial_jtag_vfs_use_nonblocking();
#endif
        esp_err_t ipc_err = esp_ipc_call_blocking(
            state->usb_serial_jtag_install_core,
            uninstall_driver, &result);
        if (ipc_err != ESP_OK) {
            result.result = ipc_err;
        }
#endif
    }
    if (result.result == ESP_OK) {
        state->driver_started = false;
    }
    state->link_up = false;
    state->reported_link_up = false;
}

static iris_link_event_t usb_serial_jtag_poll(
    iris_runtime_t *runtime, iris_transport_state_t *state)
{
    (void)runtime;
    const bool connected = state->driver_started && usb_serial_jtag_is_connected();
#if CONFIG_ESP_IRIS_CONSOLE_EXTERNAL_INPUT
    state->link_up = connected && (state->link_up || iris_console_input_available());
#else
    if (connected && !state->link_up && !state->pending_rx_valid) {
        state->pending_rx_valid = usb_serial_jtag_read_bytes(&state->pending_rx, 1, 0) == 1;
    }
    state->link_up = connected && (state->link_up || state->pending_rx_valid);
#endif
    if (state->link_up == state->reported_link_up) {
        return IRIS_LINK_EVENT_NONE;
    }
    state->reported_link_up = state->link_up;
    return state->link_up ? IRIS_LINK_EVENT_CONNECTED
                          : IRIS_LINK_EVENT_DISCONNECTED;
}

static int usb_serial_jtag_read(iris_runtime_t *runtime,
                                iris_transport_state_t *state,
                                uint8_t *buffer, size_t capacity)
{
    (void)runtime;
    if (!state->link_up) {
        return -ENOTCONN;
    }
#if CONFIG_ESP_IRIS_CONSOLE_EXTERNAL_INPUT
    return iris_console_input_read(buffer, capacity);
#else
    if (state->pending_rx_valid && capacity > 0) {
        buffer[0] = state->pending_rx;
        state->pending_rx_valid = false;
        return 1;
    }
    return usb_serial_jtag_read_bytes(buffer, capacity, 0);
#endif
}

static int usb_serial_jtag_write(iris_runtime_t *runtime,
                                 iris_transport_state_t *state,
                                 const uint8_t *buffer, size_t length)
{
    (void)runtime;
    if (!state->link_up) {
        return -ENOTCONN;
    }
    const size_t chunk = length < IRIS_USB_SERIAL_JTAG_WRITE_CHUNK
        ? length : IRIS_USB_SERIAL_JTAG_WRITE_CHUNK;
    return usb_serial_jtag_write_bytes(buffer, chunk, 0);
}

const iris_transport_ops_t g_iris_usb_serial_jtag_transport_ops = {
    .kind = ESP_IRIS_TRANSPORT_KIND_USB_SERIAL_JTAG,
    .name = "usb-serial-jtag",
    .start = usb_serial_jtag_start,
    .stop = usb_serial_jtag_stop,
    .poll = usb_serial_jtag_poll,
    .read = usb_serial_jtag_read,
    .write = usb_serial_jtag_write,
};
