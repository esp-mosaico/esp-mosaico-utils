#include "network_test.h"

#if CONFIG_ESP_IRIS_TRANSPORT_TCP
#include <stdio.h>
#include <string.h>
#include "esp_check.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "nvs.h"
#include "nvs_flash.h"

/* Fixture-only network provisioning. Wi-Fi owns the netif; the Iris worker
 * reads IP state through esp_netif and never accesses callback-owned buffers. */
static esp_netif_t *s_netif;
static const char *TAG = "iris_test_network";

static void network_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    (void)data;
    if (base == WIFI_EVENT &&
        (id == WIFI_EVENT_STA_START || id == WIFI_EVENT_STA_DISCONNECTED)) {
        const esp_err_t err = esp_wifi_connect();
        if (err != ESP_OK) ESP_LOGW(TAG, "connect: %s", esp_err_to_name(err));
    }
}

esp_err_t iris_test_network_start(void)
{
    if (!CONFIG_ESP_IRIS_TEST_WIFI_SSID[0]) return ESP_ERR_INVALID_STATE;
    ESP_RETURN_ON_ERROR(nvs_flash_init(), TAG, "NVS");
    nvs_handle_t handle;
    ESP_RETURN_ON_ERROR(nvs_open("iris_net_test", NVS_READWRITE, &handle), TAG, "open");
    uint8_t rotated = 0;
    esp_err_t err = nvs_get_u8(handle, "rotated", &rotated);
    nvs_close(handle);
    if (err != ESP_OK && err != ESP_ERR_NVS_NOT_FOUND) return err;
    ESP_RETURN_ON_ERROR(esp_iris_pairing_token_set(rotated
        ? CONFIG_ESP_IRIS_TEST_NEXT_PAIRING_TOKEN : CONFIG_ESP_IRIS_TEST_PAIRING_TOKEN), TAG, "pairing");
    ESP_RETURN_ON_ERROR(esp_netif_init(), TAG, "netif");
    ESP_RETURN_ON_ERROR(esp_event_loop_create_default(), TAG, "event loop");
    s_netif = esp_netif_create_default_wifi_sta();
    if (!s_netif) return ESP_ERR_NO_MEM;
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_RETURN_ON_ERROR(esp_wifi_init(&init), TAG, "wifi init");
    ESP_RETURN_ON_ERROR(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
        network_event, NULL), TAG, "events");
    wifi_config_t config = {0};
    strlcpy((char *)config.sta.ssid, CONFIG_ESP_IRIS_TEST_WIFI_SSID, sizeof(config.sta.ssid));
    strlcpy((char *)config.sta.password, CONFIG_ESP_IRIS_TEST_WIFI_PASSWORD, sizeof(config.sta.password));
    config.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    ESP_RETURN_ON_ERROR(esp_wifi_set_storage(WIFI_STORAGE_RAM), TAG, "RAM config");
    ESP_RETURN_ON_ERROR(esp_wifi_set_mode(WIFI_MODE_STA), TAG, "station");
    ESP_RETURN_ON_ERROR(esp_wifi_set_config(WIFI_IF_STA, &config), TAG, "config");
    return esp_wifi_start();
}

esp_err_t iris_test_network_rpc(const esp_iris_rpc_request_t *request,
                               uint8_t *response, size_t capacity,
                               size_t *size, void *user_ctx)
{
    (void)user_ctx;
    if (request->payload_size == 0) {
        esp_netif_ip_info_t info = {0};
        if (capacity < 16) return ESP_ERR_INVALID_SIZE;
        if (!s_netif) return ESP_ERR_INVALID_STATE;
        ESP_RETURN_ON_ERROR(esp_netif_get_ip_info(s_netif, &info), TAG, "IP");
        *size = (size_t)snprintf((char *)response, capacity, IPSTR, IP2STR(&info.ip));
        return ESP_OK;
    }
    if (request->payload_size != 1 || request->payload[0] > 1) return ESP_ERR_INVALID_ARG;
    nvs_handle_t handle;
    ESP_RETURN_ON_ERROR(nvs_open("iris_net_test", NVS_READWRITE, &handle), TAG, "open");
    esp_err_t err = nvs_set_u8(handle, "rotated", request->payload[0]);
    if (err == ESP_OK) err = nvs_commit(handle);
    nvs_close(handle);
    if (err == ESP_OK) err = esp_iris_pairing_token_set(request->payload[0]
        ? CONFIG_ESP_IRIS_TEST_NEXT_PAIRING_TOKEN : CONFIG_ESP_IRIS_TEST_PAIRING_TOKEN);
    *size = 0;
    return err;
}
#endif
