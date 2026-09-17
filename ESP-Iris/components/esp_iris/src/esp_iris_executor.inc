/* Included by services.c to keep private service ownership in one unit.
 * Only the protocol task submits/drains; only iris-service executes work.
 * Atomic stage release/acquire publishes the owned input and completion. */
#ifndef CONFIG_ESP_IRIS_SERVICE_IDLE_TIMEOUT_MS
#define CONFIG_ESP_IRIS_SERVICE_IDLE_TIMEOUT_MS 1000
#endif


#define IRIS_EXEC_MAX(a, b) ((a) > (b) ? (a) : (b))
#define IRIS_EXEC_RPC_BYTES (IRIS_RPC_HEADER_SIZE + CONFIG_ESP_IRIS_RPC_BODY_BYTES)
#if CONFIG_ESP_IRIS_OTA
#define IRIS_EXEC_OTA_BYTES IRIS_EXEC_MAX(104U, 4U + CONFIG_ESP_IRIS_OTA_CHUNK_BYTES)
#else
#define IRIS_EXEC_OTA_BYTES 0U
#endif
#if CONFIG_ESP_IRIS_SYSTEM_UPDATE
#define IRIS_EXEC_SYSTEM_BYTES IRIS_EXEC_MAX( \
    56U + CONFIG_ESP_IRIS_SYSTEM_UPDATE_MANIFEST_BYTES + \
        CONFIG_ESP_IRIS_SYSTEM_UPDATE_SIGNATURE_BYTES, \
    24U + CONFIG_ESP_IRIS_SYSTEM_UPDATE_CHUNK_BYTES)
#else
#define IRIS_EXEC_SYSTEM_BYTES 0U
#endif
#define IRIS_EXEC_REQUEST_BYTES IRIS_EXEC_MAX(IRIS_EXEC_RPC_BYTES, \
    IRIS_EXEC_MAX(IRIS_EXEC_OTA_BYTES, IRIS_EXEC_SYSTEM_BYTES))
#define IRIS_EXEC_RESULT_BYTES (IRIS_RPC_RESPONSE_HEADER_SIZE + CONFIG_ESP_IRIS_RPC_BODY_BYTES)
_Static_assert(IRIS_EXEC_REQUEST_BYTES <= ESP_IRIS_MAX_PAYLOAD_SIZE,
               "slow service request exceeds protocol capacity");

typedef struct {
    uint32_t session_id;
    iris_service_call_t result;
    uint8_t request[IRIS_EXEC_REQUEST_BYTES];
} iris_executor_work_t;

static void executor_work_free(iris_executor_work_t *work)
{
    if (work == NULL) return;
    free(work->result.payload);
    free(work);
}

enum { IRIS_EXEC_IDLE, IRIS_EXEC_QUEUED, IRIS_EXEC_RUNNING, IRIS_EXEC_DONE, IRIS_EXEC_RESERVED, IRIS_EXEC_DRAINING };
static struct {
    atomic_int stage;
    atomic_bool abandoned;
    atomic_bool deinit;
    atomic_bool ota_cancel;
    TaskHandle_t task;
    iris_executor_work_t *work;
    esp_iris_wire_header_t header;
    uint64_t received_us;
    esp_iris_ota_status_t ota_status;
    uint8_t ota_snapshot[25];
    size_t ota_snapshot_size;
} s_executor;

static bool executor_busy(void)
{
    return atomic_load(&s_executor.stage) != IRIS_EXEC_IDLE;
}

bool iris_services_work_pending(void)
{
    return executor_busy();
}

static bool executor_cancelled(void)
{
    return atomic_load(&s_executor.abandoned) || atomic_load(&s_executor.ota_cancel);
}

static void executor_request_ota_cancel(void)
{
    atomic_store(&s_executor.ota_cancel, true);
}

static uint32_t executor_allocated_bytes(void)
{
    taskENTER_CRITICAL(&s_services_lock);
#if !CONFIG_ESP_IRIS_SERVICE_CONTEXT_PSRAM
    const bool has_work = s_executor.work != NULL;
#endif
    const bool has_task = s_executor.task != NULL;
    taskEXIT_CRITICAL(&s_services_lock);
#if CONFIG_ESP_IRIS_SERVICE_CONTEXT_PSRAM
    const uint32_t work_bytes = 0;
#else
    const uint32_t work_bytes = has_work ? sizeof(*s_executor.work) : 0;
#endif
    return work_bytes +
        (has_task ? CONFIG_ESP_IRIS_SERVICE_STACK_SIZE : 0)
#if !CONFIG_ESP_IRIS_SERVICE_CONTEXT_PSRAM && !CONFIG_ESP_IRIS_RPC_RESPONSE_PSRAM
        + (s_executor.work != NULL ? IRIS_EXEC_RESULT_BYTES : 0)
#endif
        ;
}

static bool executor_ota_status(esp_iris_ota_status_t *out)
{
#if CONFIG_ESP_IRIS_OTA
    if (executor_busy()) {
        taskENTER_CRITICAL(&s_services_lock);
        *out = s_executor.ota_status;
        taskEXIT_CRITICAL(&s_services_lock);
        return true;
    }
#else
    (void)out;
#endif
    return false;
}

static void executor_snapshot(void)
{
#if CONFIG_ESP_IRIS_OTA
    uint8_t payload[25] = {0};
    esp_iris_ota_status_t status = {0};
    iris_service_state_t *state = service_state(false);
    size_t label_size = 0;
    if (valid_state(state) && state->ota != NULL) {
        iris_ota_t *ota = state->ota;
        esp_iris_job_info_t info = {0};
        if (ota->job != NULL) {
            (void)esp_iris_job_get_info(ota->job, &info);
        }
        status = (esp_iris_ota_status_t) {
            .job_id = info.id, .total_size = ota->total_size,
            .received_size = ota->received, .progress_permille = info.progress_permille,
            .state = info.state, .result = info.result, .active = ota->active,
        };
        iris_put_le32(payload, info.id);
        iris_put_le32(payload + 4, ota->total_size);
        iris_put_le32(payload + 8, ota->received);
        iris_put_le16(payload + 12, info.progress_permille);
        payload[14] = ota->active ? 1 : 0;
        label_size = ota->partition == NULL ? 0 : strnlen(ota->partition->label, 5);
        payload[15] = (uint8_t)label_size;
        iris_put_le32(payload + 16, (uint32_t)info.result);
        if (label_size != 0) memcpy(payload + 20, ota->partition->label, label_size);
    }
    taskENTER_CRITICAL(&s_services_lock);
    s_executor.ota_status = status;
    memcpy(s_executor.ota_snapshot, payload, sizeof(payload));
    s_executor.ota_snapshot_size = 20 + label_size;
    taskEXIT_CRITICAL(&s_services_lock);
#endif
}

static void executor_run_one(void)
{
    int queued = IRIS_EXEC_QUEUED;
    if (!atomic_compare_exchange_strong(&s_executor.stage, &queued, IRIS_EXEC_RUNNING)) {
        return;
    }
    iris_executor_work_t *work = s_executor.work;
    iris_decoded_frame_t frame = {.header = s_executor.header, .payload = work->request};
    if (!atomic_load(&s_executor.abandoned)) {
        if (frame.header.channel == ESP_IRIS_CHANNEL_CONTROL) {
            if (!handle_rpc(&work->result, &frame, s_executor.received_us)) {
                (void)handle_job(&work->result, &frame);
            }
        } else if (frame.header.channel == ESP_IRIS_CHANNEL_SYSTEM_UPDATE) {
            /* Inventory shares the channel, but has a separate read-only provider. */
            if (!iris_system_inventory_handle_frame(&work->result, &frame) &&
                !iris_system_update_handle_frame(&work->result, &frame)) {
                (void)iris_service_error(&work->result, frame.header.request_id,
                    ESP_ERR_NOT_SUPPORTED, frame.header.channel, frame.header.type);
            }
        } else {
            (void)handle_ota(&work->result, &frame);
        }
    }
    executor_snapshot();
    bool cleaned = false;
    for (;;) {
        taskENTER_CRITICAL(&s_services_lock);
        const bool abandoned = atomic_exchange(&s_executor.abandoned, false);
        const bool deinit = abandoned && atomic_exchange(&s_executor.deinit, false);
        const bool ota_cancel = atomic_exchange(&s_executor.ota_cancel, false);
        iris_service_state_t *state = s_services;
        esp_iris_job_cancel_fn cancel = NULL;
        void *ctx = NULL;
        bool cancel_pending = false;
        if (valid_state(state)) {
            for (size_t i = 0; i < CONFIG_ESP_IRIS_MAX_JOBS; ++i) {
                if (state->jobs[i].cancel_pending) {
                    state->jobs[i].cancel_pending = false;
                    cancel_pending = true;
                    cancel = state->jobs[i].cancel;
                    ctx = state->jobs[i].user_ctx;
                    break;
                }
            }
        }
        const bool system_cancel = iris_system_update_cancel_pending();
        if (!abandoned && !ota_cancel && !cancel_pending && !system_cancel) {
            atomic_store(&s_executor.stage, cleaned ? IRIS_EXEC_IDLE : IRIS_EXEC_DONE);
            taskEXIT_CRITICAL(&s_services_lock);
            break;
        }
        taskEXIT_CRITICAL(&s_services_lock);
        if (cancel != NULL) cancel(ctx);
        if (system_cancel) iris_system_update_poll_cancel();
        if (ota_cancel && valid_state(state)) ota_abort(state, ESP_ERR_INVALID_STATE);
        if (abandoned) {
            services_session_end_now();
            if (deinit) services_deinit_now();
            work->result.ready = false;
            cleaned = true;
        }
        executor_snapshot();
    }
    iris_notify_worker(&g_iris);
}

static bool executor_reap_idle(TaskHandle_t task)
{
#if CONFIG_ESP_IRIS_SERVICE_PERSISTENT
    /* Never publish a vacant task slot before FreeRTOS reclaims its stack.
     * Retaining the single instance also bounds rapid stop/start residency. */
    (void)task;
    return false;
#else
    iris_executor_work_t *work = NULL;
    taskENTER_CRITICAL(&s_services_lock);
    if (atomic_load(&s_executor.stage) == IRIS_EXEC_IDLE &&
            s_executor.task == task) {
        work = s_executor.work;
        s_executor.work = NULL;
        s_executor.task = NULL;
    }
    taskEXIT_CRITICAL(&s_services_lock);
    if (work == NULL) {
        return false;
    }
    executor_work_free(work);
    return true;
#endif
}

static void executor_worker(void *argument)
{
    (void)argument;
    for (;;) {
        const uint32_t notified = ulTaskNotifyTake(
            pdTRUE, pdMS_TO_TICKS(CONFIG_ESP_IRIS_SERVICE_IDLE_TIMEOUT_MS));
        if (notified == 0) {
            if (executor_reap_idle(xTaskGetCurrentTaskHandle())) {
                vTaskDelete(NULL);
                return;
            }
            continue;
        }
        executor_run_one();
    }
}

static esp_err_t executor_ensure(void)
{
    bool work_created = false;
    if (s_executor.work == NULL) {
        s_executor.work = heap_caps_calloc(1, sizeof(*s_executor.work),
#if CONFIG_ESP_IRIS_SERVICE_CONTEXT_PSRAM
                MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
#else
                MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
#endif
        if (s_executor.work == NULL) return ESP_ERR_NO_MEM;
        s_executor.work->result.capacity = IRIS_EXEC_RESULT_BYTES;
        s_executor.work->result.payload = heap_caps_malloc(IRIS_EXEC_RESULT_BYTES,
#if CONFIG_ESP_IRIS_SERVICE_CONTEXT_PSRAM || CONFIG_ESP_IRIS_RPC_RESPONSE_PSRAM
                MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
#else
                MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
#endif
        if (s_executor.work->result.payload == NULL) {
            free(s_executor.work);
            s_executor.work = NULL;
            return ESP_ERR_NO_MEM;
        }
        work_created = true;
    }
    if (s_executor.task == NULL &&
        xTaskCreate(executor_worker, "iris-service", CONFIG_ESP_IRIS_SERVICE_STACK_SIZE,
                    NULL, CONFIG_ESP_IRIS_TASK_PRIORITY, &s_executor.task) != pdPASS) {
        if (work_created) {
            executor_work_free(s_executor.work);
            s_executor.work = NULL;
        }
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}

static bool executor_abandon(iris_runtime_t *runtime, bool deinit)
{
    if (s_executor.work == NULL || s_executor.task == NULL) return false;
    taskENTER_CRITICAL(&s_services_lock);
    atomic_store(&s_executor.deinit, deinit || atomic_load(&s_executor.deinit));
    atomic_store(&s_executor.abandoned, true);
    executor_request_ota_cancel();
    iris_system_update_cancel_all();
    const int stage = atomic_load(&s_executor.stage);
    if (stage == IRIS_EXEC_IDLE || stage == IRIS_EXEC_DONE) {
        s_executor.work->session_id = runtime->session_id;
        atomic_store(&s_executor.stage, IRIS_EXEC_QUEUED);
    }
    taskEXIT_CRITICAL(&s_services_lock);
    xTaskNotifyGive(s_executor.task);
    return true;
}

void iris_services_deinit(iris_runtime_t *runtime)
{
    service_session_release(service_state(false));
    if (!executor_abandon(runtime, true)) services_deinit_now();
}

void iris_services_session_end(iris_runtime_t *runtime)
{
    service_session_release(service_state(false));
    if (!executor_abandon(runtime, false)) services_session_end_now();
}

#include "esp_iris_executor_dispatch.inc"
