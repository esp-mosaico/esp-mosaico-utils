/* 0.2 console, independent binding and snapshot regressions. */
static iris_decoded_frame_t console_response(iris_runtime_t *runtime)
{
    assert(runtime->tx_wire_length > 2);
    assert(runtime->tx_wire[0] == '\r' && runtime->tx_wire[1] == '\n');
    iris_decoded_frame_t result;
    assert(iris_console_frame_decode(runtime->tx_wire + 2,
        runtime->tx_wire_length - 2, false, &result) == ESP_OK);
    runtime->tx_wire_length = 0;
    return result;
}

static void test_printable_console(void)
{
    iris_runtime_t rt = {0};
    begin_session(&rt);
    assert(rt.tx_wire_length == 0 && !rt.hello_acked);
    const uint8_t command[] = "iris status\r";
    assert(feed_rx(&rt, command, sizeof(command) - 1) == sizeof(command) - 1);
    assert(memcmp(rt.tx_wire, "Iris 0.2", 8) == 0);
    rt.tx_wire_length = 0;
    const uint8_t hello[] = "iris hello\n";
    feed_rx(&rt, hello, sizeof(hello) - 1);
    iris_decoded_frame_t response = console_response(&rt);
    assert(response.header.type == ESP_IRIS_CONTROL_HELLO);
    uint8_t record[IRIS_CONSOLE_RECORD_BYTES]; size_t length;
    uint8_t binding[17] = {0, 0x12};
    esp_iris_wire_header_t header = {.channel = ESP_IRIS_CHANNEL_CONTROL,
        .type = ESP_IRIS_CONTROL_HELLO_ACK, .session_id = rt.session_id,
        .payload_size = sizeof(binding), .sequence = 1};
    assert(iris_console_frame_encode(record, sizeof(record), &header,
        binding, sizeof(binding), true, &length) == ESP_OK);
    for (size_t i = 0; i < length; ++i) feed_rx(&rt, record + i, 1);
    assert(rt.hello_acked && rt.owner_id[0] == 0x12);
    response = console_response(&rt);
    assert(response.header.type == ESP_IRIS_CONTROL_AUTH_RESULT && response.payload[0] == 1);
    iris_decoded_frame_t bulk = {.header = {.channel = ESP_IRIS_CHANNEL_FILE,
        .type = ESP_IRIS_FILE_VOLUMES_REQUEST, .session_id = rt.session_id, .request_id = 4}};
    assert(iris_services_handle_frame(&rt, &bulk, 0));
    response = console_response(&rt);
    assert(response.header.type == ESP_IRIS_CONTROL_ERROR);
    assert(iris_get_le32(response.payload) == ESP_ERR_NOT_SUPPORTED);
    end_session(&rt);
}

static void test_independent_link_binding(void)
{
    const uint8_t first[16] = {0x41}, other[16] = {0x42};
    memset(&g_iris, 0, sizeof(g_iris));
    memset(&g_iris_data, 0, sizeof(g_iris_data)); g_iris_data.data_link = true;
    assert(iris_link_claim(&g_iris_data, first) == ESP_OK); /* data first */
    g_iris_data.hello_acked = true; g_iris_data.session_id = 701;
    assert(iris_link_claim(&g_iris, other) == ESP_ERR_INVALID_STATE);
    assert(iris_link_claim(&g_iris, first) == ESP_OK);
    g_iris.hello_acked = true; g_iris.session_id = 702;
    end_session(&g_iris);
    assert(g_iris_data.hello_acked && g_iris_data.session_id == 701);
    assert(iris_link_claim(&g_iris, other) == ESP_ERR_INVALID_STATE);
    assert(iris_link_claim(&g_iris, first) == ESP_OK);
    end_session(&g_iris_data);
    assert(iris_link_claim(&g_iris, other) == ESP_OK);
    memset(&g_iris, 0, sizeof(g_iris));
}

static void test_console_snapshot_binding_crc_expiry(void)
{
    iris_service_state_t state = {.magic = IRIS_SERVICE_STATE_MAGIC};
    s_services = &state;
    state.screen = (esp_iris_screen_backend_t){test_screen_begin, test_screen_read, test_screen_end, NULL};
    iris_runtime_t rt = {.session_id = 702, .hello_acked = true};
    uint8_t payload[16] = {0};
    iris_decoded_frame_t request = {.header = {.channel = ESP_IRIS_CHANNEL_SCREEN,
        .type = ESP_IRIS_MEDIA_OPEN, .session_id = rt.session_id,
        .request_id = 90, .payload_size = 16}, .payload = payload};
    assert(iris_services_handle_frame(&rt, &request, 0));
    iris_decoded_frame_t response = console_response(&rt);
    const uint32_t stream = response.header.stream_id;
    assert(stream != 0 && iris_get_le32(response.payload + 16) == 512);
    request.header.type = ESP_IRIS_MEDIA_READ; request.header.payload_size = 8;
    iris_put_le16(payload + 4, 512);
    request.header.stream_id = stream + 1;
    assert(iris_services_handle_frame(&rt, &request, 0));
    response = console_response(&rt);
    assert(response.header.type == ESP_IRIS_CONTROL_ERROR && state.streams->capture.received == 0);
    request.header.stream_id = stream;
    assert(iris_services_handle_frame(&rt, &request, 0));
    response = console_response(&rt);
    assert(response.header.type == ESP_IRIS_MEDIA_DATA && response.header.payload_size == 524);
    assert(response.header.flags & ESP_IRIS_FLAG_STREAM_END);
    assert(iris_crc32(response.payload + 8, 512, 0) == iris_get_le32(response.payload + 520));
    assert(iris_services_handle_frame(&rt, &request, 0)); /* cannot reread a new image under this ID */
    response = console_response(&rt);
    assert(response.header.type == ESP_IRIS_CONTROL_ERROR);
    const unsigned before = screen_ends;
    now_us += IRIS_SNAPSHOT_IDLE_US + 1;
    iris_services_poll(&rt);
    assert(state.streams == NULL && screen_ends == before + 1);
    test_release_contexts(s_services); s_services = NULL;
}
