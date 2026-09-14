#include "esp_iris_memory.h"

#include <limits.h>

#include "esp_heap_caps.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"

esp_err_t esp_iris_memory_get_heap(esp_iris_heap_memory_t *out)
{
    if (out == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    *out = (esp_iris_heap_memory_t) {
        .total_internal_bytes = heap_caps_get_total_size(MALLOC_CAP_INTERNAL),
        .free_internal_bytes = heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
        .min_free_internal_bytes = heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL),
        .total_spiram_bytes = heap_caps_get_total_size(MALLOC_CAP_SPIRAM),
        .free_spiram_bytes = heap_caps_get_free_size(MALLOC_CAP_SPIRAM),
        .min_free_spiram_bytes = heap_caps_get_minimum_free_size(MALLOC_CAP_SPIRAM),
    };
    return ESP_OK;
}

esp_err_t esp_iris_memory_get_tasks(esp_iris_task_memory_t *out,
                                    size_t capacity, size_t *count)
{
    if (count == NULL || (capacity != 0 && out == NULL)) {
        return ESP_ERR_INVALID_ARG;
    }
    *count = 0;
#if CONFIG_ESP_IRIS_TASK_MEMORY_OBSERVATION
    const UBaseType_t required = uxTaskGetNumberOfTasks();
    *count = required;
    if (capacity < required || capacity > UINT_MAX ||
            capacity > SIZE_MAX / sizeof(TaskStatus_t)) {
        return ESP_ERR_INVALID_SIZE;
    }
    TaskStatus_t *statuses = heap_caps_malloc(capacity * sizeof(*statuses),
                                              MALLOC_CAP_8BIT);
    if (statuses == NULL) {
        return ESP_ERR_NO_MEM;
    }
    const UBaseType_t found = uxTaskGetSystemState(statuses, capacity, NULL);
    if (found == 0) {
        heap_caps_free(statuses);
        *count = uxTaskGetNumberOfTasks();
        return ESP_ERR_INVALID_SIZE;
    }
    size_t live = 0;
    for (UBaseType_t i = 0; i < found; ++i) {
        if (statuses[i].eCurrentState == eDeleted) {
            continue;
        }
        out[live++] = (esp_iris_task_memory_t) {
            .task_number = statuses[i].xTaskNumber,
            .stack_free_min_bytes =
                statuses[i].usStackHighWaterMark * sizeof(StackType_t),
        };
    }
    heap_caps_free(statuses);
    *count = live;
    return ESP_OK;
#else
    (void)out;
    (void)capacity;
    return ESP_ERR_NOT_SUPPORTED;
#endif
}
