/* Media control dispatch; included by services.c with its private stream state. */
static bool handle_media(iris_runtime_t *runtime,
                         const iris_decoded_frame_t *frame)
{
    const esp_iris_wire_header_t *header = &frame->header;
    const int index = media_index(header->channel);
    if (index < 0) {
        return false;
    }
    if ((header->type == ESP_IRIS_MEDIA_OPEN &&
         header->channel == ESP_IRIS_CHANNEL_SCREEN &&
         header->payload_size != IRIS_MEDIA_DESC_WIRE_SIZE) ||
        (header->type == ESP_IRIS_MEDIA_MIRROR_START &&
         header->payload_size != 20)) {
        (void)iris_queue_error(runtime, header->request_id,
                               ESP_ERR_INVALID_SIZE,
                               header->channel, header->type);
        return true;
    }
    const bool create = header->type == ESP_IRIS_MEDIA_MIRROR_START ||
                        header->type == ESP_IRIS_MEDIA_OPEN;
    capture_expire(service_state(false));
    iris_service_state_t *state = service_state(create);
    if (state == NULL || service_streams(state, create) == NULL) {
        if (header->type == ESP_IRIS_MEDIA_CLOSE &&
            header->channel == ESP_IRIS_CHANNEL_SCREEN) {
            (void)iris_queue_frame(runtime, header->channel, ESP_IRIS_MEDIA_CLOSE,
                ESP_IRIS_FLAG_RESPONSE | ESP_IRIS_FLAG_STREAM_END,
                header->request_id, header->stream_id, NULL, 0);
        } else if (header->type == ESP_IRIS_MEDIA_MIRROR_STOP) {
            (void)iris_queue_frame(runtime, header->channel,
                                   ESP_IRIS_MEDIA_MIRROR_STATE,
                                   ESP_IRIS_FLAG_RESPONSE |
                                       ESP_IRIS_FLAG_STREAM_END,
                                   header->request_id, header->stream_id,
                                   NULL, 0);
        } else {
            const esp_err_t err = create ? ESP_ERR_NO_MEM :
                (header->type == ESP_IRIS_MEDIA_OPEN
                    ? ESP_ERR_NOT_SUPPORTED : ESP_ERR_INVALID_STATE);
            (void)iris_queue_error(runtime, header->request_id, err,
                                   header->channel, header->type);
        }
        return true;
    }
    if (handle_snapshot(runtime, frame, state)) {
        return true;
    }
    if (header->type == ESP_IRIS_MEDIA_MIRROR_START) {
        iris_media_slot_t *slot = &state->streams->media[index];
        const uint16_t fps = iris_get_le16(frame->payload + 16);
        const uint16_t reserved = iris_get_le16(frame->payload + 18);
        if (slot->active || fps == 0 || fps > 60 || reserved != 0 ||
            (index == 0 && state->streams->capture.active)) {
            (void)iris_queue_error(runtime, header->request_id,
                slot->active || (index == 0 && state->streams->capture.active)
                    ? ESP_ERR_INVALID_STATE : ESP_ERR_INVALID_ARG,
                header->channel, header->type);
            return true;
        }
        esp_err_t err = ensure_media_buffer(state, slot);
        if (err != ESP_OK) {
            (void)iris_queue_error(runtime, header->request_id, err,
                                   header->channel, header->type);
            return true;
        }
        esp_iris_media_desc_t requested;
        media_desc_decode(frame->payload, &requested);
        slot->description = requested;
        slot->frame_description = requested;
        slot->pull = false;
        slot->fps = fps;
        if (index == 0 && state->screen.begin != NULL) {
            uint32_t total_size = 0;
            esp_iris_media_desc_t actual = {0};
            err = state->screen.begin(&requested, &actual, &total_size,
                                      state->screen.user_ctx);
            const bool raw = err == ESP_OK &&
                (actual.format == ESP_IRIS_PIXEL_FORMAT_RGB565 ||
                 actual.format == ESP_IRIS_PIXEL_FORMAT_RGB888);
            if (!raw || actual.stride == 0 || actual.height == 0 ||
                actual.stride > CONFIG_ESP_IRIS_MEDIA_LATEST_BYTES ||
                (uint64_t)total_size !=
                    (uint64_t)actual.stride * actual.height) {
                if (err == ESP_OK && state->screen.end != NULL) {
                    state->screen.end(state->screen.user_ctx);
                }
                release_media_buffer(state, slot);
                (void)iris_queue_error(runtime, header->request_id,
                    err != ESP_OK ? err : ESP_ERR_NOT_SUPPORTED,
                    header->channel, header->type);
                return true;
            }
            slot->description = actual;
            slot->frame_description = actual;
            slot->total_size = total_size;
            slot->offset = 0;
            slot->pull_frame_id = 1;
            slot->next_frame_us = 0;
            slot->pull = true;
        }
        slot->active = true;
        slot->session_id = runtime->session_id;
        slot->stream_id = header->stream_id != 0
            ? header->stream_id : header->request_id;
        slot->pending = false;
        slot->dropped = 0;
        slot->credit = 0;
        uint8_t response[20];
        media_desc_encode(response, &slot->frame_description);
        iris_put_le16(response + 16, fps);
        iris_put_le16(response + 18, 0);
        (void)iris_queue_frame(runtime, header->channel,
                               ESP_IRIS_MEDIA_MIRROR_STATE,
                               ESP_IRIS_FLAG_RESPONSE |
                                   ESP_IRIS_FLAG_STREAM_BEGIN,
                               header->request_id,
                               slot->stream_id,
                               response, sizeof(response));
        return true;
    }
    if (header->type == ESP_IRIS_MEDIA_MIRROR_STOP) {
        iris_media_slot_t *slot = &state->streams->media[index];
        if (header->payload_size != 0 || (slot->active &&
            (slot->session_id != runtime->session_id ||
             slot->stream_id != header->stream_id))) {
            (void)iris_queue_error(runtime, header->request_id, ESP_ERR_INVALID_STATE,
                                   header->channel, header->type);
            return true;
        }
        if (index == 0 && slot->pull && state->screen.end != NULL) {
            state->screen.end(state->screen.user_ctx);
        }
        release_media_buffer(state, slot);
        (void)iris_queue_frame(runtime, header->channel,
                               ESP_IRIS_MEDIA_MIRROR_STATE,
                               ESP_IRIS_FLAG_RESPONSE |
                                   ESP_IRIS_FLAG_STREAM_END,
                               header->request_id, header->stream_id,
                               NULL, 0);
        maybe_release_state(state);
        return true;
    }
    (void)iris_queue_error(runtime, header->request_id,
                           ESP_ERR_NOT_SUPPORTED,
                           header->channel, header->type);
    return true;
}
