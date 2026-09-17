#pragma once

#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include "lvgl.h"

typedef int esp_err_t;
#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_ERR_NO_MEM 0x101
#define ESP_ERR_INVALID_ARG 0x102
#define ESP_ERR_INVALID_STATE 0x103
#define ESP_ERR_INVALID_SIZE 0x104
#define ESP_ERR_TIMEOUT 0x107
#define ESP_ERR_NOT_ALLOWED 0x10d
#define CONFIG_ESP_IRIS_TCP_PORT 41899
#define WIFI_AUTH_OPEN 0
#define BSP_LCD_H_RES 480
#define BSP_LCD_V_RES 480
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGE(...) ((void)0)
#define ESP_RETURN_ON_FALSE(condition, error, ...) do { if (!(condition)) return (error); } while (0)
#define pdPASS 1
#define pdMS_TO_TICKS(ms) (ms)

static inline bool bsp_display_lock(int timeout) { (void)timeout; return true; }
static inline void bsp_display_unlock(void) {}
static inline lv_display_t *bsp_display_start(void) { return lv_display_get_default(); }
static inline lv_display_t *bsp_display_get(void) { return lv_display_get_default(); }
static inline int xTaskCreate(void (*task)(void *), const char *name, unsigned stack,
                              void *arg, unsigned priority, void *handle)
{
    (void)task; (void)name; (void)stack; (void)arg; (void)priority; (void)handle;
    return pdPASS; /* Status updates are driven explicitly by the test. */
}
static inline void vTaskDelay(unsigned ticks) { (void)ticks; }
