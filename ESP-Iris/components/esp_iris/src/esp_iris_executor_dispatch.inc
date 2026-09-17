/* Protocol-task dispatch and response delivery for the service executor. */
static bool executor_dispatch(iris_runtime_t *runtime,
                              const iris_decoded_frame_t *frame,
                              uint64_t received_us)
{
    const esp_iris_wire_header_t *h = &frame->header;
    const bool rpc = h->channel == ESP_IRIS_CHANNEL_CONTROL && h->type == ESP_IRIS_CONTROL_REQUEST;
    const bool cancel = h->channel == ESP_IRIS_CHANNEL_CONTROL && h->type == ESP_IRIS_CONTROL_CANCEL;
    const bool ota = h->channel == ESP_IRIS_CHANNEL_OTA;
    const bool system_update = h->channel == ESP_IRIS_CHANNEL_SYSTEM_UPDATE;
    const bool busy = executor_busy();
    if (system_update && h->type == ESP_IRIS_SYSTEM_UPDATE_STATUS) {
        return handle_service_control(runtime, frame);
    }
    if (busy) {
        if (system_update && h->type == ESP_IRIS_SYSTEM_UPDATE_CANCEL) {
            taskENTER_CRITICAL(&s_services_lock);
            const esp_err_t err = atomic_load(&s_executor.stage) == IRIS_EXEC_DONE
                ? ESP_ERR_INVALID_STATE
                : iris_system_update_request_cancel(frame->payload, h->payload_size);
            taskEXIT_CRITICAL(&s_services_lock);
            if (err != ESP_OK) {
                (void)iris_queue_error(runtime, h->request_id, err, h->channel, h->type);
            } else {
                iris_decoded_frame_t status = *frame;
                status.header.type = ESP_IRIS_SYSTEM_UPDATE_STATUS;
                status.header.payload_size = 0;
                (void)handle_service_control(runtime, &status);
            }
            return true;
        }
#if CONFIG_ESP_IRIS_OTA
        if (ota && h->type == ESP_IRIS_OTA_STATUS && h->payload_size == 0) {
            uint8_t snapshot[25]; size_t size;
            taskENTER_CRITICAL(&s_services_lock);
            size = s_executor.ota_snapshot_size;
            memcpy(snapshot, s_executor.ota_snapshot, sizeof(snapshot));
            taskEXIT_CRITICAL(&s_services_lock);
            (void)iris_queue_frame(runtime, h->channel, h->type, ESP_IRIS_FLAG_RESPONSE,
                h->request_id, iris_get_le32(snapshot), snapshot, size);
            return true;
        }
        if (ota && h->type == ESP_IRIS_OTA_CANCEL && h->payload_size == 0) {
            taskENTER_CRITICAL(&s_services_lock);
            const bool accepted = atomic_load(&s_executor.stage) != IRIS_EXEC_DONE;
            if (accepted) executor_request_ota_cancel();
            taskEXIT_CRITICAL(&s_services_lock);
            if (!accepted) {
                (void)iris_queue_error(runtime, h->request_id, ESP_ERR_INVALID_STATE, h->channel, h->type);
                return true;
            }
            /* Acknowledges intent only: no STREAM_END until the worker stops. */
            (void)iris_queue_frame(runtime, h->channel, ESP_IRIS_OTA_STATUS,
                ESP_IRIS_FLAG_RESPONSE, h->request_id, h->stream_id, NULL, 0);
            return true;
        }
#endif
        if (cancel && h->payload_size == 4) {
            iris_service_state_t *state = service_state(false);
            uint8_t payload[16]; bool found = false;
            taskENTER_CRITICAL(&s_services_lock);
            struct esp_iris_job *job = find_job(state, iris_get_le32(frame->payload));
            if (job != NULL && atomic_load(&s_executor.stage) != IRIS_EXEC_DONE) {
                found = true;
                if (job->info.state == ESP_IRIS_JOB_RUNNING) {
                    job->info.cancel_requested = true;
                    job->cancel_pending = true;
                    job->event_pending = true;
                }
                job_encode(payload, &job->info);
            }
            taskEXIT_CRITICAL(&s_services_lock);
            if (found) {
                (void)iris_queue_frame(runtime, h->channel, ESP_IRIS_CONTROL_JOB_STATUS,
                    ESP_IRIS_FLAG_RESPONSE, h->request_id, 0, payload, sizeof(payload));
            } else {
                (void)iris_queue_error(runtime, h->request_id, ESP_ERR_NOT_FOUND, h->channel, h->type);
            }
            return true;
        }
        if (h->channel == ESP_IRIS_CHANNEL_CONTROL && h->type == ESP_IRIS_CONTROL_JOB_QUERY) {
            return handle_service_control(runtime, frame);
        }
        (void)iris_queue_error(runtime, h->request_id, ESP_ERR_INVALID_STATE, h->channel, h->type);
        return true;
    }
    if (!rpc && !cancel && !ota && !system_update) return false;
    taskENTER_CRITICAL(&s_services_lock);
    const bool idle = atomic_load(&s_executor.stage) == IRIS_EXEC_IDLE;
    if (idle) {
        atomic_store(&s_executor.abandoned, false);
        atomic_store(&s_executor.deinit, false);
        atomic_store(&s_executor.ota_cancel, false);
        atomic_store(&s_executor.stage, IRIS_EXEC_RESERVED);
    }
    taskEXIT_CRITICAL(&s_services_lock);
    if (!idle) {
        (void)iris_queue_error(runtime, h->request_id, ESP_ERR_INVALID_STATE, h->channel, h->type);
        return true;
    }
    const esp_err_t err = executor_ensure();
    if (err != ESP_OK) {
        atomic_store(&s_executor.stage, IRIS_EXEC_IDLE);
        (void)iris_queue_error(runtime, h->request_id, err, h->channel, h->type);
        return true;
    }
    if (h->payload_size > IRIS_EXEC_REQUEST_BYTES) {
        atomic_store(&s_executor.stage, IRIS_EXEC_IDLE);
        (void)iris_queue_error(runtime, h->request_id, ESP_ERR_INVALID_SIZE,
            h->channel, h->type);
        return true;
    }
    if (rpc) {
        const esp_err_t admission = rpc_accept_request(frame);
        if (admission != ESP_OK) {
            atomic_store(&s_executor.stage, IRIS_EXEC_IDLE);
            (void)iris_queue_error(runtime, h->request_id, admission,
                h->channel, h->type);
            return true;
        }
    }
    executor_snapshot();
    s_executor.header = *h;
    s_executor.received_us = received_us;
    s_executor.work->session_id = runtime->session_id;
    s_executor.work->result.ready = false;
    memcpy(s_executor.work->request, frame->payload, h->payload_size);
    atomic_store(&s_executor.stage, IRIS_EXEC_QUEUED);
    xTaskNotifyGive(s_executor.task);
    return true;
}

static bool executor_queue_next(iris_runtime_t *runtime)
{
    if (runtime->tx_wire_length != 0) return false;
    taskENTER_CRITICAL(&s_services_lock);
    const bool ready = atomic_load(&s_executor.stage) == IRIS_EXEC_DONE;
    if (ready) atomic_store(&s_executor.stage, IRIS_EXEC_DRAINING);
    taskEXIT_CRITICAL(&s_services_lock);
    if (!ready) return false;
    iris_executor_work_t *work = s_executor.work;
    bool queued = false;
    bool retry = false;
    if (work->session_id == runtime->session_id && work->result.ready &&
        !atomic_load(&s_executor.abandoned)) {
        const esp_iris_wire_header_t *h = &work->result.response;
        queued = iris_queue_frame(runtime, h->channel, h->type, h->flags,
            h->request_id, h->stream_id, work->result.payload,
            h->payload_size) == ESP_OK;
        retry = !queued;
    }
    taskENTER_CRITICAL(&s_services_lock);
    const bool cleanup = atomic_load(&s_executor.abandoned);
    if (!retry) work->result.ready = false;
    atomic_store(&s_executor.stage, cleanup ? IRIS_EXEC_QUEUED :
                 (retry ? IRIS_EXEC_DONE : IRIS_EXEC_IDLE));
    taskEXIT_CRITICAL(&s_services_lock);
    if (cleanup) xTaskNotifyGive(s_executor.task);
    return queued;
}
