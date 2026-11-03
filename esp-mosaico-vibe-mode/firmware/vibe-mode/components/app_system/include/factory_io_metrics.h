// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <stddef.h>
#include <stdint.h>
#ifdef ESP_PLATFORM
#include "esp_log.h"
#include "esp_memory_utils.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#endif

/* Task-local counters: no allocation, per-chunk logging or shared state.
 * Nested records overlap. Pipelined NAND read time also overlaps NOR writes;
 * total elapsed time, not the sum of stage times, measures install latency. */
typedef struct {
    int64_t started, read, write, hash, begin, end, sync;
    int64_t yielded, yield_mark;
    uint64_t bytes;
} factory_io_metrics_t;

#define FACTORY_IO_CHUNK_BYTES (16U * 1024U)

static inline int64_t factory_io_now(void) {
#ifdef ESP_PLATFORM
    return esp_timer_get_time();
#else
    return 0;
#endif
}

/* Bound uninterrupted worker time instead of sleeping after every small IO.
 * A real one-tick block still lets idle/UI run; taskYIELD alone cannot do that
 * when they have a lower priority. Network EAGAIN keeps its own backoff. */
static inline void factory_io_cooperate(factory_io_metrics_t *m) {
#ifdef ESP_PLATFORM
    int64_t now = factory_io_now();
    int64_t mark = m->yield_mark ? m->yield_mark : m->started;
    if (now - mark < 20000) return;
    vTaskDelay(1);
    m->yield_mark = factory_io_now();
    m->yielded += m->yield_mark - now;
#else
    (void)m;
#endif
}

static inline void factory_io_report(const char *stage, const char *name,
                                      const factory_io_metrics_t *m, const void *buffer,
                                      size_t capacity, int result) {
#ifdef ESP_PLATFORM
    ESP_LOGI("io_perf", "%s name=%s bytes=%llu total_us=%lld read_us=%lld write_us=%lld "
             "hash_us=%lld begin_us=%lld end_us=%lld sync_us=%lld yield_us=%lld buffer=%s/%u result=%d "
             "task=%s core=%u stack=%p data=%p",
             stage, name, (unsigned long long)m->bytes,
             (long long)(factory_io_now() - m->started), (long long)m->read,
             (long long)m->write, (long long)m->hash, (long long)m->begin,
             (long long)m->end, (long long)m->sync, (long long)m->yielded,
             !buffer ? "none" : esp_ptr_in_dram(buffer) ? "internal" :
                 esp_ptr_external_ram(buffer) ? "psram" :
                 esp_ptr_in_rtc_dram_fast(buffer) ? "rtc" : "other",
             (unsigned)capacity, result, pcTaskGetName(NULL), (unsigned)xPortGetCoreID(),
             (const void *)&result, buffer);
#else
    (void)stage; (void)name; (void)m; (void)buffer; (void)capacity; (void)result;
#endif
}
