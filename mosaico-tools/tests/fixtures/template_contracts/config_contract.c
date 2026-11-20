// SPDX-License-Identifier: Apache-2.0
/* Exercise the real public reader, template loader and device entry point.
 * Only NVS storage, zeroization and unrelated platform/UI services are stubbed. */
#include "config_sdk.h"
#include "app_config.h"
#include "app_display.h"
#include "app_hello.h"
#include "mosaico_shared.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

static const char *saved_ssid = "private-test-ssid";
static const char *saved_password = "private-test-password";
static const char *saved_api_key = "private-test-token";
static esp_err_t init_error, open_error, read_error;
static bool handle_open, recovery_started;
static unsigned ui_starts;
static char logs[4096];

esp_err_t nvs_flash_init_partition(const char *partition)
{
    assert(!strcmp(partition, "sysmeta"));
    return init_error;
}

esp_err_t nvs_open_from_partition(const char *partition, const char *space,
                                  nvs_open_mode_t mode, nvs_handle_t *handle)
{
    assert(!strcmp(partition, "sysmeta") && !strcmp(space, "shared"));
    assert(mode == NVS_READONLY && !handle_open);
    if (open_error != ESP_OK) {
        return open_error;
    }
    *handle = 1;
    handle_open = true;
    return ESP_OK;
}

esp_err_t nvs_get_str(nvs_handle_t handle, const char *key, char *value, size_t *size)
{
    assert(handle == 1 && handle_open);
    if (read_error != ESP_OK) {
        return read_error;
    }
    const char *saved = NULL;
    if (!strcmp(key, "wifi_ssid")) {
        saved = saved_ssid;
    } else if (!strcmp(key, "wifi_password")) {
        saved = saved_password;
    } else if (!strcmp(key, "api_key")) {
        saved = saved_api_key;
    }
    if (!saved) {
        return ESP_ERR_NVS_NOT_FOUND;
    }
    const size_t required = strlen(saved) + 1;
    const size_t capacity = *size;
    *size = required;
    if (capacity < required) {
        return ESP_ERR_NVS_INVALID_LENGTH;
    }
    memcpy(value, saved, required);
    return ESP_OK;
}

void nvs_close(nvs_handle_t handle)
{
    assert(handle == 1 && handle_open);
    handle_open = false;
}

void mbedtls_platform_zeroize(void *buffer, size_t size)
{
    volatile unsigned char *bytes = buffer;
    while (size--) {
        *bytes++ = 0;
    }
}

void config_test_log(const char *tag, const char *format, ...)
{
    (void)tag;
    const size_t used = strlen(logs);
    va_list args;
    va_start(args, format);
    int written = vsnprintf(logs + used, sizeof(logs) - used, format, args);
    va_end(args);
    assert(written >= 0 && (size_t)written < sizeof(logs) - used);
}

const char *esp_err_to_name(esp_err_t err) { (void)err; return "test error"; }
esp_err_t nvs_flash_init(void) { return ESP_OK; }
esp_err_t esp_iris_boot_probe(void) { return ESP_OK; }
void iris_ota_support_start(void) { recovery_started = true; }
esp_err_t ui_bundle_open(esp_gsp_config_t *config) { (void)config; return ESP_OK; }
esp_err_t app_display_init(esp_gsp_esp_lcd_config_t *display) { (void)display; return ESP_OK; }
esp_err_t iris_screen_mirror_init(void) { return ESP_OK; }
esp_err_t iris_screen_mirror_attach(esp_gsp_handle_t ui) { (void)ui; return ESP_OK; }

esp_err_t esp_gsp_esp_lcd_start(const esp_gsp_config_t *config,
                               const esp_gsp_esp_lcd_config_t *display,
                               esp_gsp_handle_t *ui)
{
    (void)config;
    (void)display;
    *ui = NULL;
    return ESP_OK;
}

esp_gsp_err_t app_hello_create(esp_gsp_handle_t ui, app_hello_handle_t *out)
{
    (void)ui;
    assert(recovery_started);
    *out = NULL;
    ++ui_starts;
    return ESP_GSP_OK;
}

void app_main(void);

static void expect_startup(void)
{
    logs[0] = 0;
    ui_starts = 0;
    recovery_started = false;
    app_main();
    assert(recovery_started && ui_starts == 1 && !handle_open);
    if (saved_ssid && *saved_ssid) {
        assert(!strstr(logs, saved_ssid));
    }
    if (saved_password && *saved_password) {
        assert(!strstr(logs, saved_password));
    }
    assert(!strstr(logs, saved_api_key));
}

static void expect_load(esp_err_t expected)
{
    app_config_wifi_t wifi;
    memset(&wifi, 0xa5, sizeof(wifi)); /* Detect stale or partially updated output. */
    assert(app_config_load_wifi(&wifi) == expected);
    assert(!handle_open);
    if (expected == ESP_OK) {
        assert(!strcmp(wifi.ssid, saved_ssid));
        assert(!strcmp(wifi.password, saved_password));
    } else {
        const unsigned char *bytes = (const unsigned char *)&wifi;
        for (size_t i = 0; i < sizeof(wifi); ++i) {
            assert(bytes[i] == 0);
        }
    }
    expect_startup();
}

int main(void)
{
    assert(app_config_load_wifi(NULL) == ESP_ERR_INVALID_ARG);
    expect_load(ESP_OK);
    saved_ssid = "changed-network";
    expect_load(ESP_OK); /* Re-read saved values, without a stale cache. */
    saved_ssid = NULL;
    expect_load(ESP_ERR_NVS_NOT_FOUND);
    saved_ssid = "private-test-ssid";
    saved_password = NULL;
    expect_load(ESP_ERR_NVS_NOT_FOUND);
    saved_password = "";
    expect_load(ESP_OK); /* Explicitly saved open network. */
    saved_ssid = "";
    expect_load(ESP_ERR_INVALID_ARG);

    char ssid[34], password[66];
    memset(ssid, 's', 32);
    ssid[32] = 0;
    memset(password, 'A', 64);
    password[64] = 0;
    saved_ssid = ssid;
    saved_password = password;
    expect_load(ESP_OK); /* Maximum SSID and hexadecimal PSK retain every byte. */
    ssid[32] = 's'; ssid[33] = 0;
    expect_load(ESP_ERR_NVS_INVALID_LENGTH);
    ssid[32] = 0;
    password[64] = 'A'; password[65] = 0;
    expect_load(ESP_ERR_NVS_INVALID_LENGTH);
    password[64] = 0; password[0] = 'z';
    expect_load(ESP_ERR_INVALID_ARG);
    password[63] = 0;
    expect_load(ESP_OK); /* A 63-byte passphrase need not be hexadecimal. */
    saved_password = "short";
    expect_load(ESP_ERR_INVALID_ARG);
    saved_password = "invalid\x7f";
    expect_load(ESP_ERR_INVALID_ARG);
    saved_password = "abcdefgh";
    expect_load(ESP_OK);

    init_error = ESP_ERR_NVS_NO_FREE_PAGES;
    expect_load(init_error); /* No erase/recovery writes are available in this harness. */
    init_error = ESP_OK;
    open_error = ESP_ERR_NVS_NOT_FOUND;
    expect_load(open_error);
    open_error = ESP_FAIL;
    expect_load(open_error);
    open_error = ESP_OK;
    read_error = ESP_ERR_NVS_TYPE_MISMATCH;
    expect_load(read_error);
    read_error = ESP_OK;

    char custom[257];
    assert(mosaico_shared_get("api_key", custom, sizeof(custom)) == ESP_OK);
    assert(!strcmp(custom, saved_api_key) && !handle_open);
    assert(mosaico_shared_get("missing", custom, sizeof(custom)) == ESP_ERR_NVS_NOT_FOUND);
    assert(!handle_open);
    return 0;
}
