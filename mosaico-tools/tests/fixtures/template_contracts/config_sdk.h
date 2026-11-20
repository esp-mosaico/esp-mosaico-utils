// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <assert.h>
#include <stddef.h>
#include "esp_gsp.h"

typedef int esp_err_t;
enum {
    ESP_OK = 0, ESP_FAIL = -1, ESP_ERR_INVALID_ARG = 0x102,
    ESP_ERR_NVS_NOT_FOUND = 0x1102, ESP_ERR_NVS_INVALID_LENGTH = 0x110c,
    ESP_ERR_NVS_TYPE_MISMATCH = 0x1103, ESP_ERR_NVS_NO_FREE_PAGES = 0x110d,
};
typedef int nvs_handle_t;
typedef enum { NVS_READONLY, NVS_READWRITE } nvs_open_mode_t;

esp_err_t nvs_flash_init(void);
esp_err_t nvs_flash_init_partition(const char *partition);
esp_err_t nvs_open_from_partition(const char *partition, const char *space,
                                  nvs_open_mode_t mode, nvs_handle_t *handle);
esp_err_t nvs_get_str(nvs_handle_t handle, const char *key, char *value, size_t *size);
void nvs_close(nvs_handle_t handle);
void mbedtls_platform_zeroize(void *buffer, size_t size);

typedef struct { int unused; } esp_gsp_config_t;
typedef struct { int unused; } esp_gsp_esp_lcd_config_t;
esp_err_t esp_iris_boot_probe(void);
void iris_ota_support_start(void);
esp_err_t ui_bundle_open(esp_gsp_config_t *config);
esp_err_t iris_screen_mirror_init(void);
esp_err_t iris_screen_mirror_attach(esp_gsp_handle_t ui);
esp_err_t esp_gsp_esp_lcd_start(const esp_gsp_config_t *config,
                               const esp_gsp_esp_lcd_config_t *display,
                               esp_gsp_handle_t *ui);
const char *esp_err_to_name(esp_err_t err);
void config_test_log(const char *tag, const char *format, ...);
#define ESP_ERROR_CHECK(expression) assert((esp_err_t)(expression) == ESP_OK)
#define ESP_ERROR_CHECK_WITHOUT_ABORT ESP_ERROR_CHECK
#define ESP_LOGI config_test_log
#define ESP_LOGW config_test_log
#define ESP_LOGE config_test_log
