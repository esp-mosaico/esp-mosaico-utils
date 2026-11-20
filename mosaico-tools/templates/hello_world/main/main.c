// SPDX-License-Identifier: Apache-2.0
#include "app_config.h"
#include "app_display.h"
#include "app_hello.h"
#include "esp_iris.h"
#include "esp_log.h"
#include "iris_ota_support.h"
#include "iris_screen_mirror.h"
#include "mbedtls/platform_util.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "ui_bundle.h"

static const char *TAG = "hello_world";

/* The composition root retains owned handles, never controller internals. */
static struct {
    esp_gsp_handle_t ui;
    app_hello_handle_t controller;
} application;

void app_main(void)
{
    ESP_ERROR_CHECK_WITHOUT_ABORT(esp_iris_boot_probe());
    ESP_ERROR_CHECK(nvs_flash_init());
    /* Recovery must remain reachable even when the UI bundle cannot be loaded. */
    iris_ota_support_start();

    /* Provision shared credentials in Vibe Mode; consume them through app_config.
     * This example reads saved configuration. Networking owns connection policy. */
    app_config_wifi_t wifi;
    const esp_err_t wifi_err = app_config_load_wifi(&wifi);
    if (wifi_err == ESP_OK) {
        ESP_LOGI(TAG, "Shared Wi-Fi configuration available");
        /* A device networking component can consume wifi here before it is cleared. */
    } else if (wifi_err == ESP_ERR_NVS_NOT_FOUND) {
        ESP_LOGI(TAG, "Wi-Fi unconfigured; set it up in Vibe Mode");
    } else {
        ESP_LOGW(TAG, "Shared Wi-Fi configuration unavailable (%s); check Vibe Mode settings",
                 esp_err_to_name(wifi_err));
    }
    mbedtls_platform_zeroize(&wifi, sizeof(wifi));

    esp_gsp_config_t config;
    const esp_err_t err = ui_bundle_open(&config);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "GSP UI unavailable (0x%x); Recovery RPC remains active", err);
        return;
    }
    esp_gsp_esp_lcd_config_t display;
    const esp_err_t display_err = app_display_init(&display);
    if (display_err != ESP_OK) {
        ESP_LOGE(TAG, "Display unavailable (0x%x); Recovery RPC remains active", display_err);
        return;
    }
    ESP_ERROR_CHECK(iris_screen_mirror_init());
    ESP_ERROR_CHECK(esp_gsp_esp_lcd_start(&config, &display, &application.ui));
    ESP_ERROR_CHECK(iris_screen_mirror_attach(application.ui));
    ESP_ERROR_CHECK(app_hello_create(application.ui, &application.controller));
    /* GSP retains the callback context. Device UI/controller live until reboot;
     * teardown requires quiescing GSP before app_hello_destroy(), then closing UI. */
    ESP_LOGI(TAG, "GSP Hello World ready");
}
