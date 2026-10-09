/* Bounded screenshot lifecycle; included with the private service stream state.
 * The media dispatcher validates the OPEN payload and acquires state first.
 */
static bool handle_snapshot(iris_runtime_t *runtime,
                            const iris_decoded_frame_t *frame,
                            iris_service_state_t *state)
{
    const esp_iris_wire_header_t *header = &frame->header;
    if (header->type == ESP_IRIS_MEDIA_OPEN &&
        header->channel == ESP_IRIS_CHANNEL_SCREEN) {
        if (state->screen.begin == NULL || state->streams->capture.active ||
            state->streams->media[0].active) {
            (void)iris_queue_error(runtime, header->request_id,
                state->screen.begin == NULL ? ESP_ERR_NOT_SUPPORTED
                                            : ESP_ERR_INVALID_STATE,
                header->channel, header->type);
            return true;
        }
        esp_iris_media_desc_t requested;
        esp_iris_media_desc_t actual;
        media_desc_decode(frame->payload, &requested);
        uint32_t total_size = 0;
        esp_err_t err = state->screen.begin(&requested, &actual, &total_size,
                                            state->screen.user_ctx);
        if (err != ESP_OK || total_size == 0 || total_size > IRIS_SNAPSHOT_MAX_BYTES) {
            if (err == ESP_OK && state->screen.end != NULL) {
                state->screen.end(state->screen.user_ctx);
            }
            (void)iris_queue_error(runtime, header->request_id,
                                   err == ESP_OK ? ESP_ERR_INVALID_SIZE : err,
                                   header->channel, header->type);
            return true;
        }
        state->streams->capture = (iris_capture_t) {
            .active = true,
            .session_id = runtime->session_id,
            .deadline_us = esp_timer_get_time() + IRIS_SNAPSHOT_TIMEOUT_US,
            .idle_deadline_us = esp_timer_get_time() + IRIS_SNAPSHOT_IDLE_US,
            .description = actual,
            .total_size = total_size,
            .stream_id = header->request_id != 0 ? header->request_id : 1,
        };
        uint8_t payload[20];
        media_desc_encode(payload, &actual);
        iris_put_le32(payload + 16, total_size);
        (void)iris_queue_frame(runtime, header->channel,
                               ESP_IRIS_MEDIA_OPENED,
                               ESP_IRIS_FLAG_RESPONSE |
                                   ESP_IRIS_FLAG_STREAM_BEGIN,
                               header->request_id, state->streams->capture.stream_id,
                               payload, sizeof(payload));
        return true;
    }
    if (header->type == ESP_IRIS_MEDIA_READ &&
        header->channel == ESP_IRIS_CHANNEL_SCREEN) {
        if (!state->streams->capture.active || header->payload_size != 8 ||
            header->stream_id != state->streams->capture.stream_id ||
            runtime->session_id != state->streams->capture.session_id) {
            (void)iris_queue_error(runtime, header->request_id,
                                   ESP_ERR_INVALID_STATE,
                                   header->channel, header->type);
            return true;
        }
        const uint32_t offset = iris_get_le32(frame->payload);
        uint16_t maximum = iris_get_le16(frame->payload + 4);
        if (maximum > CONFIG_ESP_IRIS_MEDIA_LATEST_BYTES) {
            maximum = CONFIG_ESP_IRIS_MEDIA_LATEST_BYTES;
        }
        if (!runtime->data_link && maximum > IRIS_SNAPSHOT_CONTROL_CHUNK_BYTES)
            maximum = IRIS_SNAPSHOT_CONTROL_CHUNK_BYTES;
        if (maximum > ESP_IRIS_MAX_PAYLOAD_SIZE - 12U)
            maximum = ESP_IRIS_MAX_PAYLOAD_SIZE - 12U;
        if (maximum == 0 || frame->payload[6] != 0 || frame->payload[7] != 0 ||
            offset != state->streams->capture.received ||
            offset >= state->streams->capture.total_size) {
            (void)iris_queue_error(runtime, header->request_id,
                                   ESP_ERR_INVALID_ARG,
                                   header->channel, header->type);
            return true;
        }
        size_t size = 0;
        esp_err_t err = state->screen.read(
            offset, runtime->rx_wire + 8, maximum, &size,
            state->screen.user_ctx);
        if (err != ESP_OK || size == 0 || size > maximum ||
            offset + size > state->streams->capture.total_size) {
            (void)iris_queue_error(runtime, header->request_id,
                                   err == ESP_OK ? ESP_ERR_INVALID_SIZE : err,
                                   header->channel, header->type);
            return true;
        }
        iris_put_le32(runtime->rx_wire, offset);
        iris_put_le32(runtime->rx_wire + 4, state->streams->capture.total_size);
        state->streams->capture.received += size;
        state->streams->capture.crc32 = iris_crc32(runtime->rx_wire + 8, size,
                                                  state->streams->capture.crc32);
        state->streams->capture.idle_deadline_us = esp_timer_get_time() + IRIS_SNAPSHOT_IDLE_US;
        const bool finished = offset + size == state->streams->capture.total_size;
        if (finished) iris_put_le32(runtime->rx_wire + 8 + size,
                                    state->streams->capture.crc32);
        (void)iris_queue_frame(runtime, header->channel,
                               ESP_IRIS_MEDIA_DATA,
                               ESP_IRIS_FLAG_RESPONSE |
                                   (finished ? ESP_IRIS_FLAG_STREAM_END : 0),
                               header->request_id, state->streams->capture.stream_id,
                               runtime->rx_wire, size + 8 + (finished ? 4 : 0));
        return true;
    }
    if (header->type == ESP_IRIS_MEDIA_CLOSE &&
        header->channel == ESP_IRIS_CHANNEL_SCREEN) {
        if (header->payload_size != 0 || (state->streams->capture.active &&
            (header->stream_id != state->streams->capture.stream_id ||
             runtime->session_id != state->streams->capture.session_id))) {
            (void)iris_queue_error(runtime, header->request_id, ESP_ERR_INVALID_STATE,
                                   header->channel, header->type);
            return true;
        }
        if (state->streams->capture.active && state->screen.end != NULL) {
            state->screen.end(state->screen.user_ctx);
        }
        state->streams->capture.active = false;
        maybe_release_streams(state);
        (void)iris_queue_frame(runtime, header->channel,
                               ESP_IRIS_MEDIA_CLOSE,
                               ESP_IRIS_FLAG_RESPONSE |
                                   ESP_IRIS_FLAG_STREAM_END,
                               header->request_id, header->stream_id,
                               NULL, 0);
        return true;
    }
    return false;
}
