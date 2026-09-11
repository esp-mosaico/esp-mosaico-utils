#pragma once
#include <inttypes.h>
#include <openssl/sha.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef int esp_err_t;
#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_ERR_INVALID_ARG 1
#define ESP_ERR_INVALID_STATE 2
#define ESP_ERR_INVALID_SIZE 3
#define ESP_ERR_INVALID_RESPONSE 4
#define ESP_ERR_INVALID_VERSION 5
#define ESP_ERR_NOT_SUPPORTED 6
#define ESP_ERR_NOT_FOUND 7
#define ESP_ERR_NO_MEM 8
#define ESP_ERR_TIMEOUT 9
#define ESP_ERR_INVALID_CRC 10
#define ESP_ERR_IMAGE_INVALID 11
#define ESP_ERR_NVS_NOT_FOUND 12
#define CONFIG_IDF_TARGET_ESP32S31 1
#define CONFIG_PARTITION_TABLE_OFFSET 0x8000
#define CONFIG_BOOTLOADER_OFFSET_IN_FLASH 0x2000
#define CONFIG_ESP_IRIS_SYSTEM_UPDATE 1
#define CONFIG_IRIS_FACTORY_SYSTEM_UPDATE_BACKEND 1
#define CONFIG_SPIRAM_XIP_FROM_PSRAM 1
#define CONFIG_ESP_IRIS_SYSTEM_UPDATE_MAX_COMPONENTS 8
#define CONFIG_ESP_IRIS_SYSTEM_UPDATE_MANIFEST_BYTES 4096
#define CONFIG_IRIS_FACTORY_BRIDGE_SERVER_URL "https://flash.example.com"
#define CONFIG_IRIS_FACTORY_BRIDGE_BOARD_ID "test-s31"
#define MALLOC_CAP_SPIRAM 1
#define MALLOC_CAP_8BIT 2
#define ESP_MAC_EFUSE_FACTORY 0
#define ESP_PARTITION_TYPE_APP 0
#define ESP_PARTITION_TYPE_DATA 1
#define ESP_PARTITION_TYPE_ANY 255
#define ESP_PARTITION_SUBTYPE_ANY 255
#define ESP_PARTITION_SUBTYPE_APP_FACTORY 0
#define ESP_PARTITION_SUBTYPE_APP_OTA_0 16
#define ESP_PARTITION_SUBTYPE_APP_OTA_15 31
#define HTTP_EVENT_ON_HEADER 1
#define HTTP_METHOD_POST 1
#define HTTP_METHOD_GET 0
#define NVS_READWRITE 1
#define PSA_SUCCESS 0
#define PSA_ALG_SHA_256 1
#define PSA_HASH_OPERATION_INIT                                                        \
    {                                                                                  \
        0                                                                              \
    }
#define pdPASS 1
#define pdMS_TO_TICKS(x) (x)
#define portMUX_INITIALIZER_UNLOCKED 0
#define taskENTER_CRITICAL(x) ((void)(x))
#define taskEXIT_CRITICAL(x) ((void)(x))
typedef int portMUX_TYPE;
typedef void *TaskHandle_t;
typedef int nvs_handle_t;
typedef SHA256_CTX psa_hash_operation_t;
typedef struct {
    uint32_t offset, size;
} esp_partition_pos_t;
typedef struct {
    uint32_t address, size, erase_size;
    uint8_t type, subtype;
    char label[17];
    bool encrypted, readonly;
    void *flash_chip;
} esp_partition_t;
typedef struct {
    char version[32];
} esp_app_desc_t;
typedef struct {
    unsigned revision;
} esp_chip_info_t;
typedef struct {
    int event_id;
    const char *header_key, *header_value;
} esp_http_client_event_t;
typedef struct {
    const char *url;
    esp_err_t (*event_handler)(esp_http_client_event_t *);
    int timeout_ms;
    bool disable_auto_redirect;
    void *crt_bundle_attach;
    int buffer_size;
} esp_http_client_config_t;
typedef struct mock_http *esp_http_client_handle_t;
extern int64_t mock_time;
extern bool mock_network, mock_stop_on_delay;
extern int mock_create_fail, mock_alloc_fail, mock_commit_error, mock_writes,
    mock_commits, mock_reserved, mock_abort;
extern void (*mock_worker)(void *);
extern esp_partition_t mock_factory;
#define strlcpy mock_strlcpy
static inline size_t mock_strlcpy(char *dst, const char *src, size_t n)
{
    size_t len = strlen(src);
    if (n) {
        size_t take = len < n - 1 ? len : n - 1;
        memcpy(dst, src, take);
        dst[take] = 0;
    }
    return len;
}
static inline int64_t esp_timer_get_time(void)
{
    return mock_time;
}
static inline const char *esp_err_to_name(esp_err_t err)
{
    (void)err;
    return "mock error";
}
static inline int psa_crypto_init(void)
{
    return 0;
}
static inline int psa_hash_compute(int alg, const void *p, size_t n, uint8_t *out,
                                   size_t cap, size_t *written)
{
    (void)alg;
    (void)cap;
    SHA256(p, n, out);
    *written = 32;
    return 0;
}
static inline int psa_hash_setup(psa_hash_operation_t *h, int alg)
{
    (void)alg;
    SHA256_Init(h);
    return 0;
}
static inline int psa_hash_update(psa_hash_operation_t *h, const void *p, size_t n)
{
    SHA256_Update(h, p, n);
    return 0;
}
static inline int psa_hash_finish(psa_hash_operation_t *h, uint8_t *out, size_t cap,
                                  size_t *written)
{
    (void)cap;
    SHA256_Final(out, h);
    *written = 32;
    return 0;
}
static inline int psa_hash_abort(psa_hash_operation_t *h)
{
    (void)h;
    return 0;
}
static inline uint32_t esp_random(void)
{
    return 0;
}
static inline void esp_fill_random(void *p, size_t n)
{
    memset(p, 0x12, n);
}
static inline esp_err_t esp_read_mac(uint8_t *p, int type)
{
    (void)type;
    memset(p, 0x12, 6);
    return 0;
}
static inline bool esp_secure_boot_enabled(void)
{
    return false;
}
static inline bool esp_efuse_is_flash_encryption_enabled(void)
{
    return false;
}
static inline void esp_chip_info(esp_chip_info_t *chip)
{
    chip->revision = 100;
}
static inline const char *esp_get_idf_version(void)
{
    return "test";
}
static inline const esp_app_desc_t *esp_app_get_description(void)
{
    static esp_app_desc_t app = {"3.0-recovery"};
    return &app;
}
static inline const esp_partition_t *esp_ota_get_running_partition(void)
{
    return &mock_factory;
}
static inline esp_err_t esp_flash_get_size(void *chip, uint32_t *size)
{
    (void)chip;
    *size = 0x1000000;
    return 0;
}
static inline esp_err_t esp_flash_get_physical_size(void *chip, uint32_t *size)
{
    return esp_flash_get_size(chip, size);
}
#ifdef BACKEND_TEST
esp_err_t esp_flash_read(void *chip, void *buf, uint32_t offset, size_t size);
#else
static inline esp_err_t esp_flash_read(void *chip, void *buf, uint32_t offset,
                                       size_t size)
{
    (void)chip;
    (void)offset;
    memset(buf, 0xff, size);
    return 0;
}
#endif
static inline void *heap_caps_malloc(size_t size, int caps)
{
    (void)caps;
    return mock_alloc_fail ? NULL : malloc(size);
}
static inline int xTaskCreate(void (*fn)(void *), const char *name, int stack,
                              void *arg, int pri, TaskHandle_t *task)
{
    (void)name;
    (void)stack;
    (void)arg;
    (void)pri;
    if (mock_create_fail)
        return 0;
    mock_worker = fn;
    if (task)
        *task = (void *)1;
    return pdPASS;
}
void vTaskDelay(unsigned ms);
void vTaskDelete(void *task);
void esp_restart(void);
esp_err_t esp_ota_set_boot_partition(const esp_partition_t *partition);
const esp_partition_t *esp_partition_find_first(int type, int subtype,
                                                const char *label);
esp_err_t nvs_open_from_partition(const char *partition, const char *ns, int mode,
                                  nvs_handle_t *n);
esp_err_t nvs_get_blob(nvs_handle_t n, const char *key, void *out, size_t *size);
esp_err_t nvs_set_blob(nvs_handle_t n, const char *key, const void *out, size_t size);
esp_err_t nvs_erase_key(nvs_handle_t n, const char *key);
esp_err_t nvs_commit(nvs_handle_t n);
void nvs_close(nvs_handle_t n);
static inline int mbedtls_base64_encode(unsigned char *out, size_t cap, size_t *written,
                                        const void *in, size_t n)
{
    (void)cap;
    (void)in;
    (void)n;
    *written = 0;
    *out = 0;
    return 0;
}
#define esp_crt_bundle_attach NULL
esp_http_client_handle_t esp_http_client_init(const esp_http_client_config_t *config);
esp_err_t esp_http_client_open(esp_http_client_handle_t h, size_t length);
int esp_http_client_fetch_headers(esp_http_client_handle_t h);
int esp_http_client_get_status_code(esp_http_client_handle_t h);
int esp_http_client_read(esp_http_client_handle_t h, char *out, size_t n);
int esp_http_client_write(esp_http_client_handle_t h, const char *data, size_t n);
bool esp_http_client_is_complete_data_received(esp_http_client_handle_t h);
void esp_http_client_set_header(esp_http_client_handle_t h, const char *key,
                                const char *value);
void esp_http_client_set_method(esp_http_client_handle_t h, int method);
void esp_http_client_close(esp_http_client_handle_t h);
void esp_http_client_cleanup(esp_http_client_handle_t h);
