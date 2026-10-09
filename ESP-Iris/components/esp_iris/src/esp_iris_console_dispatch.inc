/* Single protocol worker owns console parsing; no competing stdin reader. */
static void console_reply(iris_runtime_t *runtime, const char *message)
{
    const size_t length = strlen(message);
    if (runtime->tx_wire_length != 0 || length > IRIS_CONSOLE_RECORD_BYTES) return;
    memcpy(runtime->tx_wire, message, length);
    runtime->tx_wire_length = length;
    runtime->tx_wire_offset = 0;
}

static void console_command(iris_runtime_t *runtime, size_t length)
{
    if (length > 0 && runtime->rx_wire[length - 1U] == '\r') --length;
    runtime->rx_wire[length] = 0;
    if (length == 0) return;
    if (length >= sizeof(IRIS_CONSOLE_REQUEST_PREFIX) - 1U &&
            memcmp(runtime->rx_wire, IRIS_CONSOLE_REQUEST_PREFIX,
                   sizeof(IRIS_CONSOLE_REQUEST_PREFIX) - 1U) == 0) {
        iris_decoded_frame_t frame;
        if (iris_console_frame_decode(runtime->rx_wire, length, true, &frame) == ESP_OK) {
            handle_frame(runtime, &frame, (uint64_t)esp_timer_get_time());
        } else {
            ++runtime->invalid_frames;
            console_reply(runtime, "iris: invalid 0.2 control record\r\n");
        }
        return;
    }
    const char *command = (const char *)runtime->rx_wire;
    if (strcmp(command, "iris hello") == 0) {
        (void)queue_hello(runtime);
    } else if (strcmp(command, "iris status") == 0) {
        char identity[33];
        for (size_t i = 0; i < sizeof(runtime->device_id); ++i)
            (void)snprintf(identity + i * 2U, 3, "%02x", runtime->device_id[i]);
        const esp_app_desc_t *app = esp_app_get_description();
        const int size = snprintf((char *)runtime->tx_wire, IRIS_CONSOLE_RECORD_BYTES,
            "Iris 0.2 device=%s boot=%llu project=%s version=%s healthy=%u\r\n",
            identity, (unsigned long long)runtime->boot_id,
            app->project_name, app->version, runtime->healthy ? 1U : 0U);
        if (size > 0 && (size_t)size < IRIS_CONSOLE_RECORD_BYTES) {
            runtime->tx_wire_length = (size_t)size;
            runtime->tx_wire_offset = 0;
        }
    } else if (strcmp(command, "iris") == 0 || strcmp(command, "iris help") == 0 ||
               strcmp(command, "help") == 0) {
        console_reply(runtime, "iris status  - device identity and health\r\n"
            "iris hello   - discover the 0.2 control API\r\n"
            "iris @...    - printable 0.2 request (RPC/jobs/screenshot)\r\n");
    } else {
        console_reply(runtime, "iris: unknown command; use iris help\r\n");
    }
}

static size_t feed_console(iris_runtime_t *runtime, const uint8_t *data, size_t length)
{
    for (size_t i = 0; i < length; ++i) {
        const uint8_t value = data[i];
        if (value == '\n' || value == '\r') {
            if (runtime->rx_discarding) {
                console_reply(runtime, "iris: control record too long\r\n");
            } else {
                console_command(runtime, runtime->rx_wire_length);
            }
            runtime->rx_wire_length = 0;
            runtime->rx_discarding = false;
            if (runtime->tx_wire_length != 0) return i + 1U;
        } else if (!runtime->rx_discarding) {
            if (runtime->rx_wire_length >= IRIS_CONSOLE_RECORD_BYTES - 1U) {
                ++runtime->invalid_frames;
                runtime->rx_wire_length = 0;
                runtime->rx_discarding = true;
            } else if (value == 8 || value == 127) {
                if (runtime->rx_wire_length > 0) --runtime->rx_wire_length;
            } else if (value >= 32 || value == '\r' || value == '\t') {
                runtime->rx_wire[runtime->rx_wire_length++] = value;
            } else {
                runtime->rx_discarding = true;
                ++runtime->invalid_frames;
            }
        }
    }
    return length;
}
