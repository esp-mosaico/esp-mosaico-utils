// SPDX-License-Identifier: Apache-2.0
#include "factory_ui_dispatch.h"

#include <stdatomic.h>
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"

#define UI_START_TIMEOUT_MS 5000
#define UI_REQUEST_TIMEOUT_MS 2000

typedef struct {
    uint32_t id;
    int64_t deadline;
} ui_request_t;

typedef struct {
    uint32_t id;
    esp_err_t result;
} ui_response_t;

static vibe_ui_t *s_state;
static vibe_services_t s_services;
static SemaphoreHandle_t s_initialized, s_call_lock;
static QueueHandle_t s_requests, s_responses;
static bool s_init_attempted;
static atomic_bool s_ready;
static esp_err_t s_init_result;
static uint32_t s_next_request;

static TickType_t remaining_ticks(int64_t deadline)
{
    const int64_t remaining = deadline - esp_timer_get_time();
    if (remaining <= 0) return 0;
    const TickType_t ticks = pdMS_TO_TICKS((remaining + 999) / 1000);
    return ticks > 0 ? ticks : 1;
}

static void process_commands(esp_gsp_handle_t ui, void *ctx)
{
    (void)ctx;
    if (!s_init_attempted) {
        s_init_attempted = true;
        s_init_result = vibe_ui_init(s_state, ui, &s_services);
        atomic_store(&s_ready, s_init_result == ESP_OK);
        xSemaphoreGive(s_initialized);
    }
    if (!atomic_load(&s_ready)) return;
    ui_request_t request;
    if (xQueueReceive(s_requests, &request, 0) == pdTRUE &&
            esp_timer_get_time() < request.deadline) {
        const ui_response_t response = {
            .id = request.id,
            .result = vibe_ui_open_bridge(s_state),
        };
        /* A timed-out caller owns no queued storage. A late response carries
         * its request ID and cannot complete the next caller's request. */
        xQueueOverwrite(s_responses, &response);
    }
}

esp_err_t factory_ui_dispatch_start(esp_gsp_handle_t ui, vibe_ui_t *state,
                                    const vibe_services_t *services)
{
    if (s_state != NULL) return ESP_ERR_INVALID_STATE;
    s_initialized = xSemaphoreCreateBinary();
    s_call_lock = xSemaphoreCreateMutex();
    s_requests = xQueueCreate(1, sizeof(ui_request_t));
    s_responses = xQueueCreate(1, sizeof(ui_response_t));
    if (!s_initialized || !s_call_lock || !s_requests || !s_responses) goto fail;
    s_state = state;
    s_services = *services;
    if (!esp_gsp_timer_create(ui, 50, process_commands, NULL)) goto fail;
    /* Once registered, the callback owns these resources, including after a
     * timeout. It may complete later without accessing a caller's stack. */
    if (xSemaphoreTake(s_initialized, pdMS_TO_TICKS(UI_START_TIMEOUT_MS)) != pdTRUE)
        return ESP_ERR_TIMEOUT;
    return s_init_result;
fail:
    if (s_initialized) vSemaphoreDelete(s_initialized);
    if (s_call_lock) vSemaphoreDelete(s_call_lock);
    if (s_requests) vQueueDelete(s_requests);
    if (s_responses) vQueueDelete(s_responses);
    s_initialized = s_call_lock = NULL;
    s_requests = s_responses = NULL;
    s_state = NULL;
    return ESP_ERR_NO_MEM;
}

esp_err_t factory_ui_dispatch_open_bridge(void)
{
    if (!atomic_load(&s_ready)) return ESP_ERR_INVALID_STATE;
    const int64_t deadline = esp_timer_get_time() + UI_REQUEST_TIMEOUT_MS * 1000LL;
    if (xSemaphoreTake(s_call_lock, remaining_ticks(deadline)) != pdTRUE)
        return ESP_ERR_TIMEOUT;
    const ui_request_t request = {.id = ++s_next_request, .deadline = deadline};
    /* Replace a request that expired while the render task was stalled. */
    xQueueOverwrite(s_requests, &request);
    esp_err_t result = ESP_ERR_TIMEOUT;
    ui_response_t response;
    TickType_t wait;
    while ((wait = remaining_ticks(deadline)) != 0 &&
            xQueueReceive(s_responses, &response, wait) == pdTRUE) {
        if (response.id == request.id) {
            result = response.result;
            break;
        }
    }
    xSemaphoreGive(s_call_lock);
    return result;
}
