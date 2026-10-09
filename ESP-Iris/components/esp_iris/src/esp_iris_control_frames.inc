/* Control frame encoding and pending events.
 * Included by esp_iris.c; runtime ownership and lifecycle stay in that file.
 */
typedef struct {
    uint8_t *data;
    size_t capacity;
    size_t length;
} tlv_writer_t;

static bool tlv_put(tlv_writer_t *writer, uint8_t tag, const void *value,
                    size_t length)
{
    if (length > UINT16_MAX || writer->length + 3U + length > writer->capacity) {
        return false;
    }
    writer->data[writer->length++] = tag;
    iris_put_le16(writer->data + writer->length, (uint16_t)length);
    writer->length += 2;
    if (length > 0) {
        memcpy(writer->data + writer->length, value, length);
        writer->length += length;
    }
    return true;
}

static bool tlv_put_u8(tlv_writer_t *writer, uint8_t tag, uint8_t value)
{
    return tlv_put(writer, tag, &value, sizeof(value));
}

static bool tlv_put_u16(tlv_writer_t *writer, uint8_t tag, uint16_t value)
{
    uint8_t bytes[2];
    iris_put_le16(bytes, value);
    return tlv_put(writer, tag, bytes, sizeof(bytes));
}

static bool tlv_put_u32(tlv_writer_t *writer, uint8_t tag, uint32_t value)
{
    uint8_t bytes[4];
    iris_put_le32(bytes, value);
    return tlv_put(writer, tag, bytes, sizeof(bytes));
}

static bool tlv_put_u64(tlv_writer_t *writer, uint8_t tag, uint64_t value)
{
    uint8_t bytes[8];
    iris_put_le64(bytes, value);
    return tlv_put(writer, tag, bytes, sizeof(bytes));
}

static bool tlv_put_string(tlv_writer_t *writer, uint8_t tag,
                           const char *value, size_t maximum)
{
    return tlv_put(writer, tag, value, strnlen(value, maximum));
}

static esp_err_t queue_frame(iris_runtime_t *runtime, uint8_t channel,
                             uint8_t type, uint16_t flags,
                             uint32_t request_id, uint32_t stream_id,
                             const uint8_t *payload, size_t payload_size)
{
    if (runtime->tx_wire_length != 0) {
        return ESP_ERR_INVALID_STATE;
    }
    esp_iris_wire_header_t header = {
        .channel = channel,
        .type = type,
        .flags = flags,
        .session_id = runtime->session_id,
        .request_id = request_id,
        .stream_id = stream_id,
        .sequence = ++runtime->sequence[channel],
        .payload_size = payload_size,
    };
    size_t wire_size = 0;
    esp_err_t err = runtime->data_link ? iris_frame_encode(runtime->tx_wire,
                                      ESP_IRIS_MAX_WIRE_FRAME_SIZE, &header,
                                      payload, payload_size, &wire_size)
        : iris_console_frame_encode(runtime->tx_wire + 2, IRIS_CONSOLE_RECORD_BYTES - 2,
                                    &header, payload, payload_size, false,
                                    &wire_size);
    if (err == ESP_OK) {
        if (!runtime->data_link) {
            /* A preceding partial application line cannot swallow the marker. */
            runtime->tx_wire[0] = '\r';
            runtime->tx_wire[1] = '\n';
            wire_size += 2;
        }
        runtime->tx_wire_length = wire_size;
        runtime->tx_wire_offset = 0;
    }
    return err;
}

static esp_err_t queue_error(iris_runtime_t *runtime, uint32_t request_id,
                             esp_err_t code, uint8_t channel, uint8_t type)
{
    uint8_t payload[8] = {0};
    iris_put_le32(payload, (uint32_t)code);
    payload[4] = channel;
    payload[5] = type;
    return queue_frame(runtime, ESP_IRIS_CHANNEL_CONTROL,
                       ESP_IRIS_CONTROL_ERROR,
                       ESP_IRIS_FLAG_RESPONSE | ESP_IRIS_FLAG_ERROR,
                       request_id, 0, payload, sizeof(payload));
}

esp_err_t iris_queue_frame(iris_runtime_t *runtime, uint8_t channel,
                           uint8_t type, uint16_t flags,
                           uint32_t request_id, uint32_t stream_id,
                           const uint8_t *payload, size_t payload_size)
{
    return queue_frame(runtime, channel, type, flags, request_id, stream_id,
                       payload, payload_size);
}

esp_err_t iris_queue_error(iris_runtime_t *runtime, uint32_t request_id,
                           esp_err_t code, uint8_t channel, uint8_t type)
{
    return queue_error(runtime, request_id, code, channel, type);
}

static esp_err_t queue_hello(iris_runtime_t *runtime)
{
    _Static_assert(sizeof(CONFIG_ESP_IRIS_PRODUCT_CONTRACT) <= 65 &&
                   sizeof(CONFIG_ESP_IRIS_BOARD_ID) <= 65 &&
                   sizeof(CONFIG_ESP_IRIS_LAYOUT_ID) <= 65,
                   "ESP-Iris compatibility identifiers must be at most 64 bytes");
    uint8_t payload[512];
    tlv_writer_t writer = {.data = payload, .capacity = sizeof(payload)};
    const esp_app_desc_t *app = esp_app_get_description();
    uint64_t capabilities = ESP_IRIS_CAP_LOG | ESP_IRIS_CAP_EVENT |
                                  ESP_IRIS_CAP_STATUS |
                                  ESP_IRIS_CAP_TIME_SYNC |
                                  ESP_IRIS_CAP_CRASH |
                                  iris_services_capabilities(runtime);
#if CONFIG_ESP_IRIS_CRASH_LOOP_TRACKING
    capabilities |= ESP_IRIS_CAP_CRASH_LOOP;
#endif
#if CONFIG_ESP_IRIS_TASK_MEMORY_OBSERVATION
    capabilities |= ESP_IRIS_CAP_TASK_MEMORY;
#endif
    const uint8_t transport = (uint8_t)iris_runtime_transport_kind(runtime);
    const uint8_t auth_mode = iris_services_auth_mode(runtime);
    const uint32_t reset_reason = (uint32_t)esp_reset_reason();

    if (!tlv_put(&writer, ESP_IRIS_TLV_DEVICE_ID, runtime->device_id,
                 sizeof(runtime->device_id)) ||
            !tlv_put(&writer, ESP_IRIS_TLV_HARDWARE_MAC,
                     runtime->hardware_mac, sizeof(runtime->hardware_mac)) ||
            !tlv_put_u64(&writer, ESP_IRIS_TLV_BOOT_ID, runtime->boot_id) ||
            !tlv_put_u64(&writer, ESP_IRIS_TLV_UPTIME_US,
                         (uint64_t)esp_timer_get_time()) ||
            !tlv_put_u16(&writer, ESP_IRIS_TLV_PROTOCOL_VERSION,
                         ESP_IRIS_PROTOCOL_VERSION) ||
            !tlv_put_u64(&writer, ESP_IRIS_TLV_CAPABILITIES, capabilities) ||
            !tlv_put_u8(&writer, ESP_IRIS_TLV_TRANSPORT, transport) ||
            !tlv_put_u8(&writer, ESP_IRIS_TLV_AUTH_MODE, auth_mode) ||
            !tlv_put_u32(&writer, ESP_IRIS_TLV_RESET_REASON, reset_reason) ||
            !tlv_put_string(&writer, ESP_IRIS_TLV_PROJECT_NAME,
                            app->project_name, sizeof(app->project_name)) ||
            !tlv_put_string(&writer, ESP_IRIS_TLV_APP_VERSION,
                            app->version, sizeof(app->version)) ||
            !tlv_put(&writer, ESP_IRIS_TLV_FIRMWARE_SHA256,
                     app->app_elf_sha256, sizeof(app->app_elf_sha256)) ||
            !tlv_put_string(&writer, ESP_IRIS_TLV_IDF_VERSION,
                            app->idf_ver, sizeof(app->idf_ver)) ||
            !tlv_put_u32(&writer, ESP_IRIS_TLV_MAX_PAYLOAD,
                         ESP_IRIS_MAX_PAYLOAD_SIZE) ||
            !tlv_put_u8(&writer, ESP_IRIS_TLV_FIRMWARE_ROLE,
                        CONFIG_ESP_IRIS_FIRMWARE_ROLE) ||
            !tlv_put_string(&writer, ESP_IRIS_TLV_PRODUCT_CONTRACT,
                            CONFIG_ESP_IRIS_PRODUCT_CONTRACT,
                            sizeof(CONFIG_ESP_IRIS_PRODUCT_CONTRACT)) ||
            !tlv_put_string(&writer, ESP_IRIS_TLV_CHIP_TARGET,
                            CONFIG_IDF_TARGET, sizeof(CONFIG_IDF_TARGET)) ||
            !tlv_put_string(&writer, ESP_IRIS_TLV_BOARD_ID,
                            CONFIG_ESP_IRIS_BOARD_ID, sizeof(CONFIG_ESP_IRIS_BOARD_ID)) ||
            !tlv_put_u16(&writer, ESP_IRIS_TLV_RECOVERY_ABI,
                         CONFIG_ESP_IRIS_RECOVERY_ABI) ||
            !tlv_put_u64(&writer, ESP_IRIS_TLV_REQUIRED_FEATURES, 0) ||
            !tlv_put_u32(&writer, ESP_IRIS_TLV_HEALTH_TIMEOUT_MS,
                         CONFIG_ESP_IRIS_HEALTH_TIMEOUT_MS) ||
            !tlv_put_string(&writer, ESP_IRIS_TLV_LAYOUT_ID,
                            CONFIG_ESP_IRIS_LAYOUT_ID, sizeof(CONFIG_ESP_IRIS_LAYOUT_ID))) {
        return ESP_ERR_INVALID_SIZE;
    }
    if (!tlv_put_u8(&writer, ESP_IRIS_TLV_LINK_ROLE, runtime->data_link ? 1 : 0) ||
        !tlv_put_u8(&writer, ESP_IRIS_TLV_DATA_AVAILABLE,
#if CONFIG_ESP_IRIS_DATA_LINK
                     1
#else
                     0
#endif
                     )) return ESP_ERR_INVALID_SIZE;
#if CONFIG_ESP_IRIS_TRANSPORT_TCP && CONFIG_ESP_IRIS_DATA_LINK
    if (!tlv_put_u16(&writer, ESP_IRIS_TLV_DATA_TCP_PORT,
                    CONFIG_ESP_IRIS_TCP_DATA_PORT)) return ESP_ERR_INVALID_SIZE;
#endif
    size_t challenge_size = 0;
    const uint8_t *challenge =
        iris_services_auth_challenge(runtime, &challenge_size);
    if (challenge_size > 0 &&
        !tlv_put(&writer, ESP_IRIS_TLV_AUTH_CHALLENGE,
                 challenge, challenge_size)) {
        return ESP_ERR_INVALID_SIZE;
    }
    return queue_frame(runtime, ESP_IRIS_CHANNEL_CONTROL,
                       ESP_IRIS_CONTROL_HELLO, ESP_IRIS_FLAG_RELIABLE,
                       0, 0, payload, writer.length);
}

static void schedule_event(iris_runtime_t *runtime, uint8_t type)
{
    if (type == 0 || type >= 32) {
        return;
    }
    taskENTER_CRITICAL(&runtime->event_lock);
    runtime->pending_events |= IRIS_EVENT_BIT(type);
    taskEXIT_CRITICAL(&runtime->event_lock);
    iris_notify_worker(runtime);
}

static void schedule_session_events(iris_runtime_t *runtime)
{
    const iris_runtime_t *common = common_runtime(runtime);
    schedule_event(runtime, ESP_IRIS_EVENT_BOOT);
    schedule_event(runtime, ESP_IRIS_EVENT_LINK_READY);
    if (common->previous_boot_crash) {
        schedule_event(runtime, ESP_IRIS_EVENT_PREVIOUS_BOOT_CRASH);
    }
    if (common->core_dump_present) {
        schedule_event(runtime, ESP_IRIS_EVENT_CORE_DUMP_AVAILABLE);
    }
    if (common->crash_loop_triggered) {
        schedule_event(runtime, ESP_IRIS_EVENT_CRASH_LOOP_DETECTED);
    }
    if (common->healthy) {
        schedule_event(runtime, ESP_IRIS_EVENT_HEALTHY);
    }
}

static uint8_t next_pending_event(iris_runtime_t *runtime)
{
    static const uint8_t order[] = {
        ESP_IRIS_EVENT_BOOT,
        ESP_IRIS_EVENT_LINK_READY,
        ESP_IRIS_EVENT_PREVIOUS_BOOT_CRASH,
        ESP_IRIS_EVENT_CORE_DUMP_AVAILABLE,
        ESP_IRIS_EVENT_CRASH_LOOP_DETECTED,
        ESP_IRIS_EVENT_HEALTHY,
        ESP_IRIS_EVENT_PLANNED_RESTART,
        ESP_IRIS_EVENT_RECOVERY_ENTERED,
    };
    taskENTER_CRITICAL(&runtime->event_lock);
    const uint32_t pending = runtime->pending_events;
    taskEXIT_CRITICAL(&runtime->event_lock);
    for (size_t i = 0; i < sizeof(order); ++i) {
        if ((pending & IRIS_EVENT_BIT(order[i])) != 0) {
            return order[i];
        }
    }
    return 0;
}

static esp_err_t queue_event(iris_runtime_t *runtime, uint8_t event_type)
{
    const iris_runtime_t *common = common_runtime(runtime);
    uint8_t payload[160];
    tlv_writer_t writer = {.data = payload, .capacity = sizeof(payload)};
    if (!tlv_put(&writer, ESP_IRIS_TLV_DEVICE_ID, runtime->device_id,
                 sizeof(runtime->device_id)) ||
            !tlv_put_u64(&writer, ESP_IRIS_TLV_BOOT_ID, runtime->boot_id) ||
            !tlv_put_u64(&writer, ESP_IRIS_TLV_UPTIME_US,
                         (uint64_t)esp_timer_get_time()) ||
            !tlv_put_u32(&writer, ESP_IRIS_TLV_RESET_REASON,
                         (uint32_t)esp_reset_reason()) ||
            (event_type == ESP_IRIS_EVENT_CORE_DUMP_AVAILABLE &&
             !tlv_put_u32(&writer, ESP_IRIS_TLV_CORE_DUMP_SIZE,
                          common->core_dump_size <= UINT32_MAX
                            ? (uint32_t)common->core_dump_size
                            : UINT32_MAX)) ||
            (event_type == ESP_IRIS_EVENT_CRASH_LOOP_DETECTED &&
             (!tlv_put_u32(&writer, ESP_IRIS_TLV_CRASH_COUNT,
                           common->crash_count) ||
              !tlv_put_u32(&writer, ESP_IRIS_TLV_CRASH_LIMIT,
                           common->crash_limit) ||
              !tlv_put_u8(&writer,
                          ESP_IRIS_TLV_CRASH_RECOVERY_PENDING,
                          runtime->crash_recovery_pending ? 1U : 0U) ||
              !tlv_put_u32(&writer,
                           ESP_IRIS_TLV_CRASH_ORIGIN_RESET_REASON,
                           common->crash_origin_reset_reason) ||
              !tlv_put_u32(&writer,
                           ESP_IRIS_TLV_CRASH_FAILED_APP_ADDRESS,
                           common->crash_failed_app_address) ||
              !tlv_put(&writer,
                       ESP_IRIS_TLV_CRASH_FAILED_FIRMWARE_SHA256,
                       common->crash_failed_firmware_sha256,
                       sizeof(common->crash_failed_firmware_sha256)) ||
              !tlv_put_u32(&writer, ESP_IRIS_TLV_CRASH_STATE_ERROR,
                           (uint32_t)common->crash_state_error)))) {
        return ESP_ERR_INVALID_SIZE;
    }
    esp_err_t err = queue_frame(runtime, ESP_IRIS_CHANNEL_EVENT,
                                event_type, ESP_IRIS_FLAG_RELIABLE,
                                0, 0, payload, writer.length);
    if (err == ESP_OK) {
        taskENTER_CRITICAL(&runtime->event_lock);
        runtime->pending_events &= ~IRIS_EVENT_BIT(event_type);
        taskEXIT_CRITICAL(&runtime->event_lock);
    }
    return err;
}

static esp_err_t queue_status(iris_runtime_t *runtime, uint32_t request_id)
{
    iris_runtime_t *common = common_runtime(runtime);
    uint8_t payload[320];
    tlv_writer_t writer = {.data = payload, .capacity = sizeof(payload)};
    esp_iris_heap_memory_t heap;
    esp_err_t heap_err = esp_iris_memory_get_heap(&heap);
    if (heap_err != ESP_OK) {
        return heap_err;
    }
    uint32_t dropped;
    taskENTER_CRITICAL(&common->log_lock);
    dropped = common->log_dropped_bytes;
    taskEXIT_CRITICAL(&common->log_lock);

    if (!tlv_put(&writer, ESP_IRIS_TLV_HARDWARE_MAC,
                 runtime->hardware_mac, sizeof(runtime->hardware_mac)) ||
            !tlv_put_u64(&writer, ESP_IRIS_TLV_UPTIME_US,
                     (uint64_t)esp_timer_get_time()) ||
            !tlv_put_u32(&writer, ESP_IRIS_TLV_FREE_INTERNAL,
                         heap.free_internal_bytes) ||
            !tlv_put_u32(&writer, ESP_IRIS_TLV_MIN_FREE_INTERNAL,
                         heap.min_free_internal_bytes) ||
            !tlv_put_u32(&writer, ESP_IRIS_TLV_TOTAL_INTERNAL,
                         heap.total_internal_bytes) ||
            !tlv_put_u32(&writer, ESP_IRIS_TLV_TOTAL_SPIRAM,
                         heap.total_spiram_bytes) ||
            !tlv_put_u32(&writer, ESP_IRIS_TLV_FREE_SPIRAM,
                         heap.free_spiram_bytes) ||
            !tlv_put_u32(&writer, ESP_IRIS_TLV_MIN_FREE_SPIRAM,
                         heap.min_free_spiram_bytes) ||
            !tlv_put_u32(&writer, ESP_IRIS_TLV_LOG_DROPPED, dropped) ||
            !tlv_put_u32(&writer, ESP_IRIS_TLV_RX_FRAMES,
                         runtime->rx_frames) ||
            !tlv_put_u32(&writer, ESP_IRIS_TLV_TX_FRAMES,
                         runtime->tx_frames) ||
            !tlv_put_u32(&writer, ESP_IRIS_TLV_INVALID_FRAMES,
                         runtime->invalid_frames) ||
            !tlv_put_u32(&writer, ESP_IRIS_TLV_LINK_COUNT,
                         runtime->link_count) ||
            !tlv_put_u32(&writer, ESP_IRIS_TLV_TASK_STACK_FREE_MIN,
                         common->task_stack_free_min_bytes) ||
            !tlv_put_u32(&writer, ESP_IRIS_TLV_WORKER_ACTIVE_MAX_US,
                         common->worker_active_max_us) ||
            !tlv_put_u8(&writer, ESP_IRIS_TLV_LIFECYCLE_STATE,
                        (uint8_t)common->lifecycle) ||
            !tlv_put_u32(&writer, ESP_IRIS_TLV_INTERNAL_HEAP_USED,
                         common->internal_heap_used_bytes +
                         (iris_services_allocated_bytes() >
                          common->service_bytes_at_start
                          ? iris_services_allocated_bytes() -
                            common->service_bytes_at_start : 0)) ||
            !tlv_put_u32(&writer, ESP_IRIS_TLV_STATIC_INTERNAL_BYTES,
                         runtime_static_bytes()) ||
            !tlv_put_u32(&writer, ESP_IRIS_TLV_CRASH_COUNT,
                         common->crash_count) ||
            !tlv_put_u32(&writer, ESP_IRIS_TLV_CRASH_LIMIT,
                         common->crash_limit) ||
            !tlv_put_u8(&writer, ESP_IRIS_TLV_CRASH_LOOP_TRIGGERED,
                        common->crash_loop_triggered ? 1U : 0U) ||
            !tlv_put_u8(&writer, ESP_IRIS_TLV_CRASH_RECOVERY_PENDING,
                        common->crash_recovery_pending ? 1U : 0U) ||
            !tlv_put_u32(&writer,
                         ESP_IRIS_TLV_CRASH_ORIGIN_RESET_REASON,
                         common->crash_origin_reset_reason) ||
            !tlv_put_u32(&writer, ESP_IRIS_TLV_CRASH_FAILED_APP_ADDRESS,
                         common->crash_failed_app_address) ||
            !tlv_put(&writer, ESP_IRIS_TLV_CRASH_FAILED_FIRMWARE_SHA256,
                     common->crash_failed_firmware_sha256,
                     sizeof(common->crash_failed_firmware_sha256)) ||
            !tlv_put_u32(&writer, ESP_IRIS_TLV_CRASH_STATE_ERROR,
                         (uint32_t)common->crash_state_error)) {
        return ESP_ERR_INVALID_SIZE;
    }
    return queue_frame(runtime, ESP_IRIS_CHANNEL_CONTROL,
                       ESP_IRIS_CONTROL_STATUS_RESPONSE,
                       ESP_IRIS_FLAG_RESPONSE, request_id, 0,
                       payload, writer.length);
}

static esp_err_t queue_task_memory(iris_runtime_t *runtime,
                                   uint32_t request_id)
{
#if CONFIG_ESP_IRIS_TASK_MEMORY_OBSERVATION
    _Static_assert(sizeof(esp_iris_task_memory_t) == 8,
                   "task wire record must be eight bytes");
    const size_t capacity = 12U + IRIS_MAX_TASK_MEMORY_RECORDS * 8U;
    uint8_t *payload = heap_caps_malloc(capacity, MALLOC_CAP_8BIT);
    if (payload == NULL) {
        return ESP_ERR_NO_MEM;
    }
    size_t count = 0;
    esp_err_t err = esp_iris_memory_get_tasks(
        (esp_iris_task_memory_t *)(void *)(payload + 12),
        IRIS_MAX_TASK_MEMORY_RECORDS, &count);
    if (err == ESP_OK) {
        iris_put_le64(payload, (uint64_t)esp_timer_get_time());
        iris_put_le16(payload + 8, (uint16_t)count);
        iris_put_le16(payload + 10, 0);
        for (size_t i = 0; i < count; ++i) {
            esp_iris_task_memory_t record;
            memcpy(&record, payload + 12 + i * 8, sizeof(record));
            iris_put_le32(payload + 12 + i * 8, record.task_number);
            iris_put_le32(payload + 16 + i * 8, record.stack_free_min_bytes);
        }
        err = queue_frame(runtime, ESP_IRIS_CHANNEL_CONTROL,
                          ESP_IRIS_CONTROL_TASKS_RESPONSE,
                          ESP_IRIS_FLAG_RESPONSE, request_id, 0,
                          payload, 12U + count * 8U);
    }
    heap_caps_free(payload);
    return err;
#else
    (void)runtime;
    (void)request_id;
    return ESP_ERR_NOT_SUPPORTED;
#endif
}
