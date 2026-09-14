#pragma once

#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    size_t total_internal_bytes;
    size_t free_internal_bytes;
    size_t min_free_internal_bytes;
    size_t total_spiram_bytes;
    size_t free_spiram_bytes;
    size_t min_free_spiram_bytes;
} esp_iris_heap_memory_t;

typedef struct {
    uint32_t task_number;
    uint32_t stack_free_min_bytes;
} esp_iris_task_memory_t;

/** Read the allocator's current and per-region historical minimum free bytes. */
esp_err_t esp_iris_memory_get_heap(esp_iris_heap_memory_t *out);

/**
 * Snapshot all tasks' lifetime minimum free stack bytes. Values are bytes in
 * ESP-IDF FreeRTOS. Task numbers identify this boot's tasks, including tasks
 * with duplicate names; deleted tasks may disappear between polls.
 *
 * The caller owns `out`. On ESP_ERR_INVALID_SIZE, `*count` contains the latest
 * required capacity. CONFIG_ESP_IRIS_TASK_MEMORY_OBSERVATION must be enabled.
 */
esp_err_t esp_iris_memory_get_tasks(esp_iris_task_memory_t *out,
                                    size_t capacity, size_t *count);

#ifdef __cplusplus
}
#endif
