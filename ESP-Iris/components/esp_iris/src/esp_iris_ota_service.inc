/* OTA request handling; included by esp_iris_services.c. */
#if CONFIG_ESP_IRIS_OTA
static void ota_reset_without_finish(iris_service_state_t *state)
{
    iris_ota_t *ota = state->ota;
    if (ota == NULL) return;
    if (ota->hash_active) {
        (void)psa_hash_abort(&ota->hash);
    }
    taskENTER_CRITICAL(&s_services_lock);
    state->ota = NULL;
    taskEXIT_CRITICAL(&s_services_lock);
    service_context_free(state, ota, sizeof(*ota));
}

static void ota_job_cancel(void *user_ctx)
{
    (void)user_ctx;
    executor_request_ota_cancel();
}

static const esp_partition_t *ota_partition_at(uint32_t address)
{
    esp_partition_iterator_t iterator = esp_partition_find(
        ESP_PARTITION_TYPE_APP, ESP_PARTITION_SUBTYPE_ANY, NULL);
    while (iterator != NULL) {
        const esp_partition_t *partition = esp_partition_get(iterator);
        if (partition != NULL && partition->address == address) {
            esp_partition_iterator_release(iterator);
            return partition;
        }
        iterator = esp_partition_next(iterator);
    }
    esp_partition_iterator_release(iterator);
    return NULL;
}

static const esp_partition_t *ota_select_target(void)
{
    const esp_partition_t *candidate = esp_ota_get_next_update_partition(NULL);
    if (candidate == NULL) {
        return NULL;
    }
    uint32_t address = candidate->address;
    if (esp_iris_platform_select_ota_target(candidate->address, &address) !=
        ESP_OK) {
        return NULL;
    }
    return ota_partition_at(address);
}

static bool handle_ota(iris_service_call_t *runtime,
                       const iris_decoded_frame_t *frame)
{
    const esp_iris_wire_header_t *header = &frame->header;
    if (header->channel != ESP_IRIS_CHANNEL_OTA) {
        return false;
    }
    if (header->type == ESP_IRIS_OTA_BEGIN && ota_select_target() == NULL) {
        (void)iris_service_error(runtime, header->request_id,
                               ESP_ERR_NOT_FOUND,
                               header->channel, header->type);
        return true;
    }
    const bool create = header->type == ESP_IRIS_OTA_BEGIN;
    iris_service_state_t *state = service_state(create);
    if (state == NULL) {
        (void)iris_service_error(runtime, header->request_id,
                               create ? ESP_ERR_NO_MEM : ESP_ERR_INVALID_STATE,
                               header->channel, header->type);
        return true;
    }
    iris_ota_t empty = {0};
    iris_ota_t *ota = state->ota != NULL ? state->ota : &empty;
    if (header->type == ESP_IRIS_OTA_STATUS) {
        if (header->payload_size != 0) {
            (void)iris_service_error(runtime, header->request_id,
                                   ESP_ERR_INVALID_SIZE,
                                   header->channel, header->type);
            return true;
        }
        uint8_t payload[25] = {0};
        esp_iris_job_info_t info = {0};
        if (ota->job != NULL) {
            (void)esp_iris_job_get_info(ota->job, &info);
        }
        iris_put_le32(payload, info.id);
        iris_put_le32(payload + 4, ota->total_size);
        iris_put_le32(payload + 8, ota->received);
        iris_put_le16(payload + 12, info.progress_permille);
        payload[14] = ota->active ? 1 : 0;
        const size_t label_size = ota->partition != NULL
            ? strnlen(ota->partition->label, 5) : 0;
        payload[15] = (uint8_t)label_size;
        iris_put_le32(payload + 16, (uint32_t)info.result);
        if (label_size > 0) {
            memcpy(payload + 20, ota->partition->label, label_size);
        }
        (void)iris_service_reply(runtime, header->channel,
                               ESP_IRIS_OTA_STATUS,
                               ESP_IRIS_FLAG_RESPONSE,
                               header->request_id, info.id,
                               payload, 20 + label_size);
        return true;
    }
    if (header->type == ESP_IRIS_OTA_BEGIN) {
        if (ota->active || header->payload_size < IRIS_OTA_BEGIN_FIXED_SIZE) {
            (void)iris_service_error(runtime, header->request_id,
                ota->active ? ESP_ERR_INVALID_STATE : ESP_ERR_INVALID_SIZE,
                header->channel, header->type);
            return true;
        }
        const uint32_t total_size = iris_get_le32(frame->payload);
        const uint8_t project_length = frame->payload[36];
        const uint8_t version_length = frame->payload[37];
        if (project_length >= sizeof(ota->project_name) ||
            version_length >= sizeof(ota->version) ||
            header->payload_size != IRIS_OTA_BEGIN_FIXED_SIZE +
                                    project_length + version_length) {
            (void)iris_service_error(runtime, header->request_id,
                                   ESP_ERR_INVALID_SIZE,
                                   header->channel, header->type);
            return true;
        }
        const esp_partition_t *partition = ota_select_target();
        const esp_partition_t *running = esp_ota_get_running_partition();
        if (partition == NULL || running == NULL || partition == running ||
            partition->type != ESP_PARTITION_TYPE_APP ||
            total_size == 0 || total_size > partition->size) {
            (void)iris_service_error(runtime, header->request_id,
                                   ESP_ERR_NOT_FOUND,
                                   header->channel, header->type);
            return true;
        }
        if (state->ota == NULL) {
            ota = service_context_alloc(state, sizeof(*ota));
            if (ota == NULL) {
                (void)iris_service_error(runtime, header->request_id, ESP_ERR_NO_MEM,
                    header->channel, header->type);
                return true;
            }
            taskENTER_CRITICAL(&s_services_lock);
            state->ota = ota;
            taskEXIT_CRITICAL(&s_services_lock);
        }
        memset(ota, 0, sizeof(*ota));
        ota->partition = partition;
        ota->total_size = total_size;
        memcpy(ota->expected_sha256, frame->payload + 4, 32);
        memcpy(ota->project_name, frame->payload + 40, project_length);
        memcpy(ota->version, frame->payload + 40 + project_length,
               version_length);
        esp_err_t err = esp_iris_job_create(0x100, ota_job_cancel, state,
                                            &ota->job);
        if (err == ESP_OK) {
            ota->hash = psa_hash_operation_init();
            err = psa_crypto_init() == PSA_SUCCESS &&
                  psa_hash_setup(&ota->hash, PSA_ALG_SHA_256) == PSA_SUCCESS
                ? ESP_OK : ESP_FAIL;
            ota->hash_active = err == ESP_OK;
        }
        if (err == ESP_OK) {
            /*
             * A full erase here can block the protocol worker for longer than
             * the host's request deadline on large application partitions.
             * OTA DATA is strictly sequential, so let esp_ota_write() erase
             * sectors incrementally and keep BEGIN responsive.
             */
            err = esp_ota_begin(partition, OTA_WITH_SEQUENTIAL_WRITES,
                                &ota->handle);
        }
        if (err != ESP_OK) {
            if (ota->job != NULL) {
                (void)esp_iris_job_finish(ota->job, err);
            }
            ota_reset_without_finish(state);
            (void)iris_service_error(runtime, header->request_id, err,
                                   header->channel, header->type);
            return true;
        }
        ota->active = true;
        uint8_t payload[16] = {0};
        esp_iris_job_info_t info;
        (void)esp_iris_job_get_info(ota->job, &info);
        iris_put_le32(payload, info.id);
        iris_put_le32(payload + 4, total_size);
        iris_put_le16(payload + 8, CONFIG_ESP_IRIS_OTA_CHUNK_BYTES);
        const size_t label_size = strnlen(partition->label, 5);
        payload[10] = (uint8_t)label_size;
        memcpy(payload + 11, partition->label, label_size);
        (void)iris_service_reply(runtime, header->channel,
                               ESP_IRIS_OTA_BEGIN_RESPONSE,
                               ESP_IRIS_FLAG_RESPONSE |
                                   ESP_IRIS_FLAG_STREAM_BEGIN,
                               header->request_id, info.id,
                               payload, 11 + label_size);
        return true;
    }
    if (!ota->active) {
        (void)iris_service_error(runtime, header->request_id,
                               ESP_ERR_INVALID_STATE,
                               header->channel, header->type);
        return true;
    }
    if (header->type == ESP_IRIS_OTA_CANCEL) {
        if (ota->job != NULL) {
            taskENTER_CRITICAL(&s_services_lock);
            ota->job->info.cancel_requested = true;
            taskEXIT_CRITICAL(&s_services_lock);
        }
        ota_abort(state, ESP_ERR_INVALID_STATE);
        (void)iris_service_reply(runtime, header->channel,
                               ESP_IRIS_OTA_STATUS,
                               ESP_IRIS_FLAG_RESPONSE |
                                   ESP_IRIS_FLAG_STREAM_END,
                               header->request_id, header->stream_id,
                               NULL, 0);
        return true;
    }
    if (header->type == ESP_IRIS_OTA_DATA) {
        if (header->payload_size <= 4 ||
            header->payload_size - 4 > CONFIG_ESP_IRIS_OTA_CHUNK_BYTES ||
            iris_get_le32(frame->payload) != ota->received ||
            ota->received + header->payload_size - 4 > ota->total_size) {
            (void)iris_service_error(runtime, header->request_id,
                                   ESP_ERR_INVALID_SIZE,
                                   header->channel, header->type);
            return true;
        }
        const uint8_t *data = frame->payload + 4;
        const size_t size = header->payload_size - 4;
        esp_err_t err = psa_hash_update(&ota->hash, data, size) == PSA_SUCCESS
            ? esp_ota_write(ota->handle, data, size) : ESP_FAIL;
        if (err != ESP_OK) {
            ota_abort(state, err);
            (void)iris_service_error(runtime, header->request_id, err,
                                   header->channel, header->type);
            return true;
        }
        ota->received += size;
        uint16_t progress = (uint16_t)(
            ((uint64_t)ota->received * 900U) / ota->total_size);
        (void)esp_iris_job_update(ota->job, progress);
        uint8_t payload[8];
        iris_put_le32(payload, ota->received);
        iris_put_le16(payload + 4, progress);
        iris_put_le16(payload + 6, 0);
        (void)iris_service_reply(runtime, header->channel,
                               ESP_IRIS_OTA_DATA_RESPONSE,
                               ESP_IRIS_FLAG_RESPONSE, header->request_id,
                               header->stream_id, payload, sizeof(payload));
        return true;
    }
    if (header->type == ESP_IRIS_OTA_END) {
        esp_err_t err = ota->received == ota->total_size
            ? ESP_OK : ESP_ERR_INVALID_SIZE;
        uint8_t digest[32];
        size_t digest_size = 0;
        if (err == ESP_OK &&
            psa_hash_finish(&ota->hash, digest, sizeof(digest),
                            &digest_size) != PSA_SUCCESS) {
            err = ESP_FAIL;
        }
        ota->hash_active = false;
        if (err == ESP_OK &&
            (digest_size != sizeof(digest) ||
             !constant_time_equal(digest, ota->expected_sha256,
                                  sizeof(digest)))) {
            err = ESP_ERR_INVALID_CRC;
        }
        if (err == ESP_OK) {
            err = esp_ota_end(ota->handle);
        } else {
            (void)esp_ota_abort(ota->handle);
        }
        esp_app_desc_t description;
        if (err == ESP_OK) {
            err = esp_ota_get_partition_description(ota->partition,
                                                    &description);
        }
        if (err == ESP_OK && ota->project_name[0] != '\0' &&
            strncmp(description.project_name, ota->project_name,
                    sizeof(description.project_name)) != 0) {
            err = ESP_ERR_INVALID_VERSION;
        }
        if (err == ESP_OK && ota->version[0] != '\0' &&
            strncmp(description.version, ota->version,
                    sizeof(description.version)) != 0) {
            err = ESP_ERR_INVALID_VERSION;
        }
#if CONFIG_ESP_IRIS_OTA_REQUIRE_PROJECT_NAME_MATCH
        const esp_app_desc_t *running_description = esp_app_get_description();
        if (err == ESP_OK &&
            strncmp(description.project_name,
                    running_description->project_name,
                    sizeof(description.project_name)) != 0) {
            err = ESP_ERR_INVALID_VERSION;
        }
#endif
        const esp_partition_t *running = esp_ota_get_running_partition();
        if (err == ESP_OK) {
            err = esp_iris_platform_prepare_ota(
                running != NULL ? running->address : 0,
                ota->partition->address);
        }
        /* This is the final cancellable boundary. Once selection begins,
         * cancellation cannot promise to undo the committed boot target. */
        if (err == ESP_OK && executor_cancelled()) {
            err = ESP_ERR_INVALID_STATE;
        }
        if (err == ESP_OK) {
            /* A fully verified replacement image starts a new crash-history
             * scope. Do this at the final commit boundary, not OTA_BEGIN, so
             * a failed or cancelled transfer preserves existing evidence. */
            err = esp_iris_crash_loop_reset();
        }
        if (err == ESP_OK) {
            err = esp_ota_set_boot_partition(ota->partition);
        }
        esp_iris_job_handle_t job = ota->job;
        uint32_t job_id = 0;
        if (job != NULL) {
            esp_iris_job_info_t info;
            (void)esp_iris_job_finish(job, err);
            (void)esp_iris_job_get_info(job, &info);
            job_id = info.id;
        }
        uint8_t payload[8];
        iris_put_le32(payload, job_id);
        iris_put_le32(payload + 4, (uint32_t)err);
        ota_reset_without_finish(state);
        (void)iris_service_reply(runtime, header->channel,
                               ESP_IRIS_OTA_END_RESPONSE,
                               ESP_IRIS_FLAG_RESPONSE |
                                   ESP_IRIS_FLAG_STREAM_END |
                                   (err == ESP_OK ? 0 : ESP_IRIS_FLAG_ERROR),
                               header->request_id, job_id,
                               payload, sizeof(payload));
        return true;
    }
    (void)iris_service_error(runtime, header->request_id,
                           ESP_ERR_NOT_SUPPORTED,
                           header->channel, header->type);
    return true;
}
#else
static bool handle_ota(iris_service_call_t *runtime,
                       const iris_decoded_frame_t *frame)
{
    if (frame->header.channel != ESP_IRIS_CHANNEL_OTA) {
        return false;
    }
    (void)iris_service_error(runtime, frame->header.request_id,
                           ESP_ERR_NOT_SUPPORTED, frame->header.channel,
                           frame->header.type);
    return true;
}
#endif
