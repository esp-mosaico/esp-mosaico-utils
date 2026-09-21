#include "iris_bridge.h"
#include "system_plan.h"
#include "cJSON.h"
#include "esp_app_desc.h"
#include "esp_chip_info.h"
#include "esp_crt_bundle.h"
#include "esp_flash.h"
#include "esp_efuse.h"
#include "esp_heap_caps.h"
#include "esp_http_client.h"
#include "esp_mac.h"
#include "esp_ota_ops.h"
#include "esp_random.h"
#include "esp_secure_boot.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "factory_system_metadata.h"
#include "factory_system_update.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "mbedtls/base64.h"
#include "nvs.h"
#include "psa/crypto.h"
#include "sdkconfig.h"
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define LIMIT 98304 /* 32 KiB manifest plus bounded image descriptors. */
static iris_bridge_config_t cfg;
static char session[80], token[160], boot_id[33], mac[18];
static atomic_bool stop_requested;
static atomic_bool bridge_running;
static atomic_bool bridge_active;
static int last_http_status;
static unsigned retry_after_seconds;
static int64_t last_cancel_check;
static bool cancelled;
static char server_url[IRIS_BRIDGE_ORIGIN_BYTES];
static char board_id[IRIS_BRIDGE_BOARD_BYTES];
static char device_id[33];
static portMUX_TYPE snapshot_lock = portMUX_INITIALIZER_UNLOCKED;
static iris_bridge_snapshot_t snapshot = {.state = "IDLE"};
static int64_t code_deadline;

static void set_state(const char *state, unsigned progress, esp_err_t error)
{
    taskENTER_CRITICAL(&snapshot_lock);
    strlcpy(snapshot.state, state, sizeof(snapshot.state));
    snapshot.progress = progress;
    snapshot.error = error;
    if (strcmp(state, "PAIRING") != 0) {
        memset(snapshot.code, 0, sizeof(snapshot.code));
        snapshot.expires_at[0] = 0;
        code_deadline = 0;
    }
    taskEXIT_CRITICAL(&snapshot_lock);
}

void iris_bridge_get_snapshot(iris_bridge_snapshot_t *out)
{
    if (out == NULL) {
        return;
    }
    const int64_t now = esp_timer_get_time();
    taskENTER_CRITICAL(&snapshot_lock);
    *out = snapshot;
    out->running = atomic_load(&bridge_running);
    out->expires_in_ms = code_deadline > now ? (code_deadline - now) / 1000 : 0;
    taskEXIT_CRITICAL(&snapshot_lock);
    if (out->code[0] && out->expires_in_ms == 0) {
        memset(out->code, 0, sizeof(out->code));
        strlcpy(out->state, "EXPIRED", sizeof(out->state));
    }
}

static const char *str(const cJSON *o, const char *key)
{
    const cJSON *v = cJSON_GetObjectItemCaseSensitive(o, key);
    return cJSON_IsString(v) ? v->valuestring : "";
}
static uint32_t num(const cJSON *o, const char *key)
{
    const cJSON *v = cJSON_GetObjectItemCaseSensitive(o, key);
    return cJSON_IsNumber(v) && v->valuedouble >= 0 && v->valuedouble <= UINT32_MAX
               ? (uint32_t)v->valuedouble
               : 0;
}
static void hex(const uint8_t *in, size_t n, char *out)
{
    static const char h[] = "0123456789abcdef";
    for (size_t i = 0; i < n; i++) {
        out[2 * i] = h[in[i] >> 4];
        out[2 * i + 1] = h[in[i] & 15];
    }
    out[n * 2] = 0;
}
static bool digest(const void *p, size_t n, uint8_t out[32])
{
    size_t written = 0;
    return psa_hash_compute(PSA_ALG_SHA_256, p, n, out, 32, &written) == PSA_SUCCESS &&
           written == 32;
}
static bool matches(const void *p, size_t n, const char *expected)
{
    uint8_t d[32];
    char h[65];
    if (!digest(p, n, d))
        return false;
    hex(d, 32, h);
    return strcmp(h, expected) == 0;
}
static bool flash_hash(uint32_t offset, uint32_t size, char out[65])
{
    uint8_t buf[1024], hash[32];
    size_t written = 0;
    psa_hash_operation_t h = PSA_HASH_OPERATION_INIT;
    if (psa_hash_setup(&h, PSA_ALG_SHA_256) != PSA_SUCCESS)
        return false;
    for (uint32_t pos = 0; pos < size;) {
        size_t n = size - pos;
        if (n > sizeof(buf))
            n = sizeof(buf);
        if (esp_flash_read(NULL, buf, offset + pos, n) != ESP_OK ||
            psa_hash_update(&h, buf, n) != PSA_SUCCESS) {
            psa_hash_abort(&h);
            return false;
        }
        pos += n;
    }
    if (psa_hash_finish(&h, hash, 32, &written) != PSA_SUCCESS || written != 32) {
        psa_hash_abort(&h);
        return false;
    }
    hex(hash, 32, out);
    return true;
}
/* No redirects, same configured HTTPS origin, bounded reads and TLS trust
 * bundle. */
static esp_err_t response_header(esp_http_client_event_t *event)
{
    if (event->event_id == HTTP_EVENT_ON_HEADER && event->header_key &&
        event->header_value && !strcasecmp(event->header_key, "Retry-After")) {
        char *end = NULL;
        unsigned long seconds = strtoul(event->header_value, &end, 10);
        if (end != event->header_value && !*end && seconds <= 3600)
            retry_after_seconds = (unsigned)seconds;
    }
    return ESP_OK;
}
static esp_http_client_handle_t open_request(const char *path, const char *body)
{
    last_http_status = 0;
    retry_after_seconds = 0;
    char url[768], auth[180];
    if (path[0] != '/' ||
        snprintf(url, sizeof(url), "%s%s", cfg.server_url, path) >= (int)sizeof(url))
        return NULL;
    esp_http_client_config_t c = {.url = url,
                                  .event_handler = response_header,
                                  .timeout_ms = 15000,
                                  .disable_auto_redirect = true,
                                  .crt_bundle_attach = esp_crt_bundle_attach,
                                  .buffer_size = 4096};
    esp_http_client_handle_t h = esp_http_client_init(&c);
    if (!h)
        return NULL;
    if (token[0]) {
        snprintf(auth, sizeof(auth), "Bearer %s", token);
        esp_http_client_set_header(h, "Authorization", auth);
    }
    esp_http_client_set_header(h, "Content-Type", "application/json");
    esp_http_client_set_method(h, body ? HTTP_METHOD_POST : HTTP_METHOD_GET);
    size_t length = body ? strlen(body) : 0;
    if (esp_http_client_open(h, length) != ESP_OK)
        goto fail;
    for (size_t done = 0; done < length;) {
        int n = esp_http_client_write(h, body + done, length - done);
        if (n <= 0)
            goto fail;
        done += n;
    }
    if (esp_http_client_fetch_headers(h) < 0)
        goto fail;
    last_http_status = esp_http_client_get_status_code(h);
    if (last_http_status < 200 || last_http_status >= 300)
        goto fail;
    return h;
fail:
    esp_http_client_close(h);
    esp_http_client_cleanup(h);
    return NULL;
}
static cJSON *request(const char *path, const cJSON *body)
{
    int64_t deadline = esp_timer_get_time() + 30000000;
    char *encoded = body ? cJSON_PrintUnformatted(body) : NULL;
    if (body && !encoded)
        return NULL;
    esp_http_client_handle_t h = open_request(path, encoded);
    free(encoded);
    if (!h)
        return NULL;
    char *buf = malloc(LIMIT + 1);
    size_t used = 0;
    cJSON *result = NULL;
    if (buf) {
        while (used < LIMIT && esp_timer_get_time() < deadline) {
            int n = esp_http_client_read(h, buf + used, LIMIT - used);
            if (n < 0)
                break;
            if (n == 0) {
                if (esp_http_client_is_complete_data_received(h)) {
                    buf[used] = 0;
                    result = cJSON_ParseWithLength(buf, used + 1);
                }
                break;
            }
            used += n;
        }
        free(buf);
    }
    esp_http_client_close(h);
    esp_http_client_cleanup(h);
    return result;
}
static void path_session(char out[256], const char *suffix)
{
    snprintf(out, 256, "/api/v1/device-sessions/%s%s", session, suffix);
}
static bool event(const char *state, unsigned progress, esp_err_t error)
{
    set_state(state, progress, error);
    char path[256];
    path_session(path, "/progress");
    cJSON *j = cJSON_CreateObject();
    cJSON_AddStringToObject(j, "phase", state);
    cJSON_AddNumberToObject(j, "progress", progress);
    if (error != ESP_OK)
        cJSON_AddStringToObject(j, "error", esp_err_to_name(error));
    cJSON *r = request(path, j);
    bool ok = r != NULL;
    cancelled |= atomic_load(&stop_requested);
    if (r)
        cancelled |=
            cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(r, "cancel_requested"));
    cJSON_Delete(r);
    cJSON_Delete(j);
    return ok;
}
static bool should_cancel(void)
{
    if (atomic_load(&stop_requested)) {
        cancelled = true;
        return true;
    }
    int64_t now = esp_timer_get_time();
    if (now - last_cancel_check < 5000000)
        return cancelled;
    last_cancel_check = now;
    char path[256];
    path_session(path, "/poll");
    cJSON *r = request(path, NULL);
    if (!r &&
        (last_http_status == 401 || last_http_status == 404 || last_http_status == 410))
        cancelled = true;
    if (r) {
        const cJSON *o = cJSON_GetObjectItemCaseSensitive(r, "flash");
        cancelled =
            cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(o, "cancel_requested"));
        cJSON_Delete(r);
    }
    return cancelled;
}
static cJSON *identity(void)
{
    cJSON *j = cJSON_CreateObject();
    cJSON_AddStringToObject(j, "chip", "esp32s31");
    cJSON_AddNumberToObject(j, "chip_id", 32);
    cJSON_AddStringToObject(j, "profile_id", "iris-s31-layout-v1");
    cJSON_AddStringToObject(j, "mac", mac);
    cJSON_AddStringToObject(j, "device_id", cfg.device_id);
    cJSON_AddStringToObject(j, "boot_id", boot_id);
    return j;
}
typedef struct {
    uint32_t version;
    char target[17];
    char table_hash[65];
} boot_record_t;
static esp_err_t save_boot(const cJSON *plan)
{
    const char *target = str(plan, "boot_partition");
    if (!*target || !strcmp(target, "factory"))
        return ESP_OK;
    if (strlen(target) > 16)
        return ESP_ERR_INVALID_ARG;
    boot_record_t rec = {.version = 1};
    strlcpy(rec.target, target, sizeof(rec.target));
    strlcpy(rec.table_hash, str(plan, "target_table_sha256"), sizeof(rec.table_hash));
    nvs_handle_t n;
    esp_err_t err =
        nvs_open_from_partition("sysmeta", "iris_bridge", NVS_READWRITE, &n);
    if (err != ESP_OK)
        return err;
    err = nvs_set_blob(n, "pending_boot", &rec, sizeof(rec));
    if (err == ESP_OK)
        err = nvs_commit(n);
    nvs_close(n);
    return err;
}
esp_err_t iris_bridge_resume_boot(void)
{
    if (psa_crypto_init() != PSA_SUCCESS)
        return ESP_FAIL;
    nvs_handle_t n;
    esp_err_t err =
        nvs_open_from_partition("sysmeta", "iris_bridge", NVS_READWRITE, &n);
    if (err == ESP_ERR_NVS_NOT_FOUND)
        return ESP_OK;
    if (err != ESP_OK)
        return err;
    boot_record_t rec;
    size_t size = sizeof(rec);
    err = nvs_get_blob(n, "pending_boot", &rec, &size);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        nvs_close(n);
        return ESP_OK;
    }
    const esp_err_t read_error = err;
    /* Consume malformed records too, before any boot selection. */
    err = nvs_erase_key(n, "pending_boot");
    if (err == ESP_OK)
        err = nvs_commit(n);
    nvs_close(n);
    if (err != ESP_OK)
        return err;
    if (read_error != ESP_OK)
        return read_error;
    char hash[65];
    if (size != sizeof(rec) || rec.version != 1 || rec.target[16] ||
        rec.table_hash[64] || !flash_hash(0x8000, 4096, hash) ||
        strcmp(hash, rec.table_hash))
        return ESP_ERR_INVALID_VERSION;
    const esp_partition_t *p = esp_partition_find_first(
        ESP_PARTITION_TYPE_APP, ESP_PARTITION_SUBTYPE_ANY, rec.target);
    if (!p || p->address < 0x200000 || p->subtype < ESP_PARTITION_SUBTYPE_APP_OTA_0 ||
        p->subtype > ESP_PARTITION_SUBTYPE_APP_OTA_15)
        return ESP_ERR_INVALID_ARG;
    err = esp_ota_set_boot_partition(p);
    if (err == ESP_OK)
        esp_restart();
    return err;
}
static bool inventory(void)
{
    uint8_t raw[4096];
    unsigned char encoded[5500];
    size_t n;
    char hash[65], path[256];
    uint32_t flash = 0, physical = 0;
    if (esp_flash_read(NULL, raw, 0x8000, sizeof(raw)) != ESP_OK ||
        esp_flash_get_size(NULL, &flash) != ESP_OK ||
        esp_flash_get_physical_size(NULL, &physical) != ESP_OK ||
        mbedtls_base64_encode(encoded, sizeof(encoded), &n, raw, sizeof(raw)) != 0)
        return false;
    encoded[n] = 0;
    cJSON *j = identity();
    esp_chip_info_t chip;
    esp_chip_info(&chip);
    cJSON_AddNumberToObject(j, "revision", chip.revision);
    cJSON_AddStringToObject(j, "board_id", cfg.board_id);
    cJSON_AddStringToObject(j, "recovery_version", esp_app_get_description()->version);
    cJSON_AddStringToObject(j, "idf_version", esp_get_idf_version());
    cJSON_AddNumberToObject(j, "flash_size", flash);
    cJSON_AddNumberToObject(j, "physical_flash_size", physical);
    cJSON_AddNumberToObject(j, "bootloader_offset", 0x2000);
    cJSON_AddNumberToObject(j, "partition_table_offset", 0x8000);
    if (!flash_hash(0x2000, 0x6000, hash))
        goto fail;
    cJSON_AddStringToObject(j, "bootloader_sha256", hash);
    if (!flash_hash(0x8000, 0x1000, hash))
        goto fail;
    cJSON_AddStringToObject(j, "partition_table_sha256", hash);
    cJSON_AddStringToObject(j, "partition_table_bin", (char *)encoded);
    cJSON_AddStringToObject(j, "running_partition",
                            esp_ota_get_running_partition()->label);
    cJSON_AddBoolToObject(j, "secure_boot", esp_secure_boot_enabled());
    cJSON_AddBoolToObject(j, "flash_encryption", esp_efuse_is_flash_encryption_enabled());
    cJSON *caps = cJSON_AddArrayToObject(j, "capabilities");
    cJSON_AddItemToArray(caps, cJSON_CreateString("write_partitions"));
    cJSON_AddItemToArray(caps, cJSON_CreateString("replace_layout"));
    cJSON_AddItemToArray(caps, cJSON_CreateString("select_boot"));
    if (cfg.enable_factory_update)
        cJSON_AddItemToArray(caps, cJSON_CreateString("factory_update"));
    if (cfg.enable_system_update)
        cJSON_AddItemToArray(caps, cJSON_CreateString("system_update"));
    if (cfg.enable_system_update && cfg.enable_bootloader_update)
        cJSON_AddItemToArray(caps, cJSON_CreateString("bootloader_update"));
    factory_sysmeta_record_t previous;
    if (factory_system_metadata_load_last_result(&previous) == ESP_OK) {
        char ophex[33];
        hex(previous.operation_id, 16, ophex);
        cJSON_AddStringToObject(j, "last_operation_id", ophex);
        cJSON_AddStringToObject(j, "last_operation_state",
                                previous.result == ESP_OK ? "DONE" : "INTERRUPTED");
    }
    path_session(path, "/inventory");
    cJSON *r = request(path, j);
    bool ok = r != NULL;
    cJSON_Delete(r);
    cJSON_Delete(j);
    return ok;
fail:
    cJSON_Delete(j);
    return false;
}
static esp_err_t get_table(const cJSON *plan, uint8_t raw[4096])
{
    uint32_t size = num(plan, "table_size");
    if (!size || size > 4096)
        return ESP_ERR_INVALID_SIZE;
    const char *id = str(plan, "table_upload_id");
    if (!*id || strchr(id, '/'))
        return ESP_ERR_INVALID_ARG;
    char path[256];
    snprintf(path, sizeof(path), "/api/v1/device-sessions/%s/files/%s", session, id);
    esp_http_client_handle_t h = open_request(path, NULL);
    if (!h)
        return ESP_FAIL;
    memset(raw, 0xff, 4096);
    size_t received = 0;
    esp_err_t err = ESP_FAIL;
    const int64_t deadline = esp_timer_get_time() + 30000000;
    while (received < size) {
        if (should_cancel() || esp_timer_get_time() >= deadline)
            goto done;
        int n = esp_http_client_read(h, (char *)raw + received, size - received);
        if (n <= 0)
            goto done;
        received += n;
    }
    char extra;
    if (esp_http_client_read(h, &extra, 1) != 0 ||
        !esp_http_client_is_complete_data_received(h))
        goto done;
    if (matches(raw, size, str(plan, "table_sha256")) &&
        matches(raw, 4096, str(plan, "target_table_sha256")))
        err = ESP_OK;
done:
    esp_http_client_close(h);
    esp_http_client_cleanup(h);
    return err;
}
static cJSON *component(unsigned id, const char *kind, uint32_t offset, uint32_t size,
                        const char *sha, const char *file)
{
    cJSON *j = cJSON_CreateObject();
    cJSON_AddNumberToObject(j, "id", id);
    cJSON_AddStringToObject(j, "kind", kind);
    cJSON_AddNumberToObject(j, "target_offset", offset);
    cJSON_AddNumberToObject(j, "size", size);
    cJSON_AddStringToObject(j, "sha256", sha);
    cJSON_AddStringToObject(j, "file", file);
    return j;
}
static esp_err_t transfer(const char *file, const esp_iris_system_update_component_t *c,
                          const uint8_t *table)
{
    esp_http_client_handle_t h = NULL;
    uint8_t buf[4096], hash[32];
    size_t written = 0;
    uint32_t received = 0;
    esp_err_t err = ESP_FAIL;
    psa_hash_operation_t digest_op = PSA_HASH_OPERATION_INIT;
    if (!table) {
        char path[256];
        snprintf(path, sizeof(path), "/api/v1/device-sessions/%s/files/%s", session,
                 file);
        h = open_request(path, NULL);
        if (!h)
            return ESP_FAIL;
    }
    if (psa_hash_setup(&digest_op, PSA_ALG_SHA_256) != PSA_SUCCESS)
        goto done;
    size_t preloaded = 0;
    if (c->kind == ESP_IRIS_SYSTEM_UPDATE_COMPONENT_APPLICATION ||
        c->kind == ESP_IRIS_SYSTEM_UPDATE_COMPONENT_RECOVERY) {
        if (c->size < 24) {
            err = ESP_ERR_IMAGE_INVALID;
            goto done;
        }
        if (table) {
            memcpy(buf, table, 24);
            preloaded = 24;
        } else
            while (preloaded < 24) {
                int n =
                    esp_http_client_read(h, (char *)buf + preloaded, 24 - preloaded);
                if (n <= 0) {
                    err = ESP_FAIL;
                    goto done;
                }
                preloaded += n;
            }
        esp_chip_info_t chip;
        esp_chip_info(&chip);
        uint32_t flash = 0;
        esp_flash_get_size(NULL, &flash);
        uint16_t min = (uint16_t)buf[15] | ((uint16_t)buf[16] << 8),
                 max = (uint16_t)buf[17] | ((uint16_t)buf[18] << 8);
        unsigned capacity = buf[3] >> 4, speed = buf[3] & 15;
        if (buf[0] != 0xe9 || !buf[1] || buf[1] > 16 || buf[12] != 32 || buf[13] != 0 ||
            chip.revision < min || (max != 0 && max != 65535 && chip.revision > max) ||
            buf[2] > 5 || (speed > 2 && speed != 15) || capacity > 7 ||
            ((uint64_t)1 << 20 << capacity) > flash || buf[23] > 1) {
            err = ESP_ERR_IMAGE_INVALID;
            goto done;
        }
    }
    err = factory_system_update_source_begin_component(
        FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE, c);
    if (err != ESP_OK)
        goto done;
    while (received < c->size) {
        if (should_cancel()) {
            err = ESP_ERR_INVALID_STATE;
            goto done;
        }
        size_t wanted = c->size - received;
        if (wanted > sizeof(buf))
            wanted = sizeof(buf);
        int n;
        if (preloaded) {
            n = preloaded;
            preloaded = 0;
        } else if (table) {
            memcpy(buf, table + received, wanted);
            n = wanted;
        } else
            n = esp_http_client_read(h, (char *)buf, wanted);
        if (n <= 0) {
            err = ESP_FAIL;
            goto done;
        }
        if (psa_hash_update(&digest_op, buf, n) != PSA_SUCCESS) {
            err = ESP_FAIL;
            goto done;
        }
        err = factory_system_update_source_write_component(
            FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE, c, received, buf, n);
        if (err != ESP_OK)
            goto done;
        received += n;
    }
    if (h) {
        char extra;
        if (esp_http_client_read(h, &extra, 1) != 0 ||
            !esp_http_client_is_complete_data_received(h)) {
            err = ESP_ERR_INVALID_SIZE;
            goto done;
        }
    }
    if (psa_hash_finish(&digest_op, hash, 32, &written) != PSA_SUCCESS ||
        written != 32) {
        err = ESP_FAIL;
        goto done;
    }
    err = factory_system_update_source_end_component(FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE,
                                                     c, hash);
done:
    psa_hash_abort(&digest_op);
    if (h) {
        esp_http_client_close(h);
        esp_http_client_cleanup(h);
    }
    return err;
}

/* Backend validates target partition types and bounds; transport never grants
 * Flash permission. */
static esp_err_t execute(const char *op, const cJSON *plan)
{
    cancelled = atomic_load(&stop_requested);
    if (cancelled)
        return ESP_ERR_INVALID_STATE;
    last_cancel_check = esp_timer_get_time();
    const char *mode = str(plan, "mode");
    bool system = strcmp(mode, "system_update") == 0;
    bool layout = strcmp(mode, "layout") == 0;
    bool factory = strcmp(mode, "factory") == 0;
    if ((system && !cfg.enable_system_update) ||
        (factory && !cfg.enable_factory_update) ||
        (!system && !layout && !factory && strcmp(mode, "partitions") != 0))
        return ESP_ERR_NOT_SUPPORTED;
    if (system) {
        esp_err_t policy = iris_bridge_validate_system_plan(plan, cfg.enable_bootloader_update, cfg.enable_factory_update);
        if (policy != ESP_OK)
            return policy;
    }
    if (factory) {
        const cJSON *m = cJSON_GetObjectItemCaseSensitive(plan, "factory_manifest");
        if (strcmp(str(m, "profile_id"), "iris-s31-layout-v1") ||
            strcmp(str(m, "board_id"), cfg.board_id) ||
            num(m, "protocol_version") != 1 || !*str(m, "recovery_version"))
            return ESP_ERR_INVALID_VERSION;
    }
    uint8_t *recovery = NULL;
    uint8_t opid[16], table[4096];
    if (strlen(op) != 32)
        return ESP_ERR_INVALID_ARG;
    for (size_t i = 0; i < 16; i++) {
        unsigned byte;
        char part[3] = {op[i * 2], op[i * 2 + 1], 0};
        if (strspn(part, "0123456789abcdef") != 2 || sscanf(part, "%2x", &byte) != 1)
            return ESP_ERR_INVALID_ARG;
        opid[i] = byte;
    }

    esp_err_t err =
        factory_system_update_source_reserve(FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE, opid);
    if (err != ESP_OK)
        return err;
    char source_hash[65];
    if (!flash_hash(0x8000, 4096, source_hash) ||
        strcmp(source_hash, str(plan, "source_table_sha256"))) {
        err = ESP_ERR_INVALID_VERSION;
        goto abort;
    }
    if (system) {
        const cJSON *manifest = cJSON_GetObjectItemCaseSensitive(plan, "system_manifest");
        err = factory_system_update_source_prepare_bridge(
            manifest, opid, cfg.enable_bootloader_update);
        if (err != ESP_OK)
            goto abort;
        goto prepared;
    }
    if (layout) {
        err = get_table(plan, table);
        if (err != ESP_OK)
            goto abort;
    }
    if (factory) {
        const cJSON *images = cJSON_GetObjectItemCaseSensitive(plan, "images");
        const cJSON *im = cJSON_GetArrayItem(images, 0);
        uint32_t length = num(im, "size");
        const char *file = str(im, "upload_id");
        if (cJSON_GetArraySize(images) != 1 ||
            strcmp(str(im, "partition"), "factory") || !length || length > 0x1c0000 ||
            !*file || strchr(file, '/')) {
            err = ESP_ERR_INVALID_ARG;
            goto abort;
        }
        recovery = heap_caps_malloc(0x1c0000, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        if (!recovery) {
            err = ESP_ERR_NO_MEM;
            goto abort;
        }
        memset(recovery, 0xff, 0x1c0000);
        char path[256];
        snprintf(path, sizeof(path), "/api/v1/device-sessions/%s/files/%s", session,
                 file);
        esp_http_client_handle_t h = open_request(path, NULL);
        if (!h) {
            err = ESP_FAIL;
            goto abort;
        }
        uint32_t done = 0;
        const int64_t deadline = esp_timer_get_time() + 25LL * 60 * 1000000;
        while (done < length) {
            if (should_cancel() || esp_timer_get_time() >= deadline)
                break;
            size_t wanted = length - done;
            if (wanted > 4096)
                wanted = 4096;
            int n = esp_http_client_read(h, (char *)recovery + done, wanted);
            if (n <= 0)
                break;
            done += n;
        }
        char extra;
        bool complete = !should_cancel() && done == length &&
                        esp_http_client_read(h, &extra, 1) == 0 &&
                        esp_http_client_is_complete_data_received(h);
        esp_http_client_close(h);
        esp_http_client_cleanup(h);
        if (!complete || !matches(recovery, length, str(im, "sha256"))) {
            err = ESP_ERR_INVALID_CRC;
            goto abort;
        }
    }
    cJSON *root = cJSON_CreateObject(),
          *target = cJSON_AddObjectToObject(root, "target"),
          *items = cJSON_AddArrayToObject(root, "components");
    uint32_t size = 0;
    esp_flash_get_size(NULL, &size);
    cJSON_AddStringToObject(root, "schema", "esp-iris-system-update/v1");
    cJSON_AddBoolToObject(root, "preserve_layout", !layout);
    cJSON_AddStringToObject(root, "target_layout_sha256",
                            str(plan, "target_table_sha256"));
    cJSON_AddNumberToObject(target, "chip_id", 32);
    cJSON_AddNumberToObject(target, "flash_size", size);
    unsigned index = 1;
    if (layout)
        cJSON_AddItemToArray(items,
                             component(index++, "partition_table", 0x8000, 4096,
                                       str(plan, "target_table_sha256"), "table"));
    const cJSON *im = NULL;
    cJSON_ArrayForEach(im, cJSON_GetObjectItemCaseSensitive(plan, "images"))
    {
        const char *name = str(im, "partition");
        const esp_partition_t *p = esp_partition_find_first(
            ESP_PARTITION_TYPE_ANY, ESP_PARTITION_SUBTYPE_ANY, name);
        /* For new layouts, read type from validated raw table, never infer from
         * label. */
        unsigned type = p ? p->type : 255;
        if (layout) {
            type = 255;
            for (size_t off = 0; off + 32 <= 0xc00; off += 32) {
                if (table[off] != 0xaa || table[off + 1] != 0x50)
                    continue;
                uint32_t addr;
                memcpy(&addr, table + off + 4, 4);
                if (addr == num(im, "offset")) {
                    type = table[off + 2];
                    break;
                }
            }
        }
        if (type > 1 || !*str(im, "upload_id") || strchr(str(im, "upload_id"), '/')) {
            cJSON_Delete(root);
            err = ESP_ERR_INVALID_ARG;
            goto abort;
        }
        if (factory) {
            uint8_t hash[32];
            char h[65];
            if (!digest(recovery, 0x1c0000, hash)) {
                cJSON_Delete(root);
                err = ESP_FAIL;
                goto abort;
            }
            hex(hash, 32, h);
            cJSON_AddItemToArray(items, component(index++, "recovery", 0x20000,
                                                  0x1c0000, h, str(im, "upload_id")));
        } else
            cJSON_AddItemToArray(items,
                                 component(index++, type == 0 ? "application" : "data",
                                           num(im, "offset"), num(im, "size"),
                                           str(im, "sha256"), str(im, "upload_id")));
    }
    char *json = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (!json) {
        err = ESP_ERR_NO_MEM;
        goto abort;
    }
    err = factory_system_update_source_prepare(FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE,
                                               (uint8_t *)json, strlen(json), opid);
    free(json);
    if (err != ESP_OK)
        goto abort;
prepared:;
    size_t count = factory_system_update_source_component_count(
        FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE);
    if (!event("WRITING", 0, ESP_OK) || cancelled) {
        err = ESP_ERR_INVALID_STATE;
        goto abort;
    }
    for (size_t i = 0; i < count; i++) {
        esp_iris_system_update_component_t c;
        char file[FACTORY_SYSTEM_UPDATE_FILENAME_BYTES];
        err = factory_system_update_source_component(FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE,
                                                     i, &c, file);
        if (err != ESP_OK)
            goto abort;
        err = transfer(file, &c,
                       !system && c.kind == ESP_IRIS_SYSTEM_UPDATE_COMPONENT_PARTITION_TABLE
                           ? table
                           : (factory ? recovery : NULL));
        if (err != ESP_OK)
            goto abort;
        if (!event("WRITING", (i + 1) * 90 / count, ESP_OK) || cancelled) {
            err = ESP_ERR_INVALID_STATE;
            goto abort;
        }
    }
    if (!event("VERIFYING", 95, ESP_OK) || cancelled || atomic_load(&stop_requested)) {
        err = ESP_ERR_INVALID_STATE;
        goto abort;
    }
    /* A successful COMMITTING acknowledgement authorizes the critical write.
     * A local stop arriving after that acknowledgement cannot revoke it. */
    if (!event("COMMITTING", 98, ESP_OK)) {
        err = ESP_ERR_INVALID_STATE;
        goto abort;
    }
    err = factory_system_update_source_commit(FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE, opid);
    if (err != ESP_OK) {
        /* A failed readback or metadata write may follow a physical table write.
         * Discard all cached descriptors after an attempted critical commit. */
        if (factory_system_update_source_needs_restart(
                FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE)) {
            event("FAILED", 100, err);
            free(recovery);
            esp_restart();
        }
        goto abort;
    }
    free(recovery);
    recovery = NULL;
    err = save_boot(plan);
    event(err == ESP_OK ? "DONE" : "FAILED", 100, err);
    memset(session, 0, sizeof(session));
    memset(token, 0, sizeof(token));
    /* The raw layout may have changed: never resume with a stale IDF cache. */
    esp_restart();
    return ESP_OK;
abort:
    free(recovery);
    factory_system_update_source_abort(FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE, opid, err);
    return err;
}
static void run(void *unused)
{
    (void)unused;
    unsigned backoff = 5;
    unsigned registration_failures = 0;
    int64_t pairing_deadline = 0;
    set_state("WAITING_NETWORK", 0, ESP_OK);
    while (!atomic_load(&stop_requested) && cfg.network_ready && !cfg.network_ready()) {
        vTaskDelay(pdMS_TO_TICKS(250));
    }
    if (!atomic_load(&stop_requested))
        set_state("REGISTERING", 0, ESP_OK);
    while (!atomic_load(&stop_requested)) {
        if (pairing_deadline && esp_timer_get_time() >= pairing_deadline) {
            set_state("EXPIRED", 0, ESP_ERR_TIMEOUT);
            if (!atomic_load(&bridge_active)) break;
            /* A visible download page renews an expired, unpaired session.
             * Idle prefetch expires instead of registering forever. */
            memset(session, 0, sizeof(session));
            memset(token, 0, sizeof(token));
            pairing_deadline = 0;
            registration_failures = 0;
            set_state("REGISTERING", 0, ESP_OK);
        }
        if (session[0] && !atomic_load(&bridge_active)) {
            vTaskDelay(pdMS_TO_TICKS(250));
            continue;
        }
        if (!session[0]) {
            const int64_t registered_at = esp_timer_get_time();
            cJSON *j = identity();
            cJSON *r = request("/api/v1/device-sessions", j);
            cJSON_Delete(j);
            if (r) {
                const char *id = str(r, "session_id");
                const char *secret = str(r, "auth_token");
                const char *code = str(r, "device_code");
                if (strlen(id) != 32 || !*secret || strlen(secret) >= sizeof(token) ||
                    !*code || strlen(code) >= IRIS_BRIDGE_CODE_BYTES) {
                    cJSON_Delete(r);
                    set_state("FAILED", 0, ESP_ERR_INVALID_RESPONSE);
                    break;
                }
                strlcpy(session, id, sizeof(session));
                strlcpy(token, secret, sizeof(token));
                pairing_deadline = registered_at + 600LL * 1000000;
                set_state("PAIRING", 0, ESP_OK);
                taskENTER_CRITICAL(&snapshot_lock);
                strlcpy(snapshot.code, code, sizeof(snapshot.code));
                strlcpy(snapshot.expires_at, str(r, "expires_at"),
                        sizeof(snapshot.expires_at));
                code_deadline = pairing_deadline;
                taskEXIT_CRITICAL(&snapshot_lock);
                cJSON_Delete(r);
                backoff = 5;
            } else {
                if (++registration_failures >= 3) {
                    set_state("FAILED", 0, ESP_FAIL);
                    break;
                }
                backoff = backoff < 30 ? backoff * 2 : 60;
            }
        } else {
            char path[256];
            path_session(path, "/poll");
            cJSON *r = request(path, NULL);
            /* A page may close during a blocking HTTP request. Never promote
             * a background session into inventory/update work on its reply. */
            if (!atomic_load(&bridge_active)) {
                cJSON_Delete(r);
                continue;
            }
            if (r) {
                backoff = 5;
                if (cJSON_IsTrue(
                        cJSON_GetObjectItemCaseSensitive(r, "inventory_required"))) {
                    pairing_deadline = 0;
                    set_state("PAIRED", 0, ESP_OK);
                    inventory();
                }
                const cJSON *flash = cJSON_GetObjectItemCaseSensitive(r, "flash");
                if (!atomic_load(&stop_requested) && atomic_load(&bridge_active) &&
                    !strcmp(str(flash, "phase"), "QUEUED")) {
                    /* Never replay after an uncertain PRECHECK acknowledgement. */
                    path_session(path, "/progress");
                    cJSON *start = cJSON_CreateObject();
                    cJSON_AddStringToObject(start, "phase", "PRECHECK");
                    cJSON_AddNumberToObject(start, "progress", 0);
                    set_state("PRECHECK", 0, ESP_OK);
                    cJSON *accepted = request(path, start);
                    cJSON_Delete(start);
                    esp_err_t err = ESP_ERR_INVALID_RESPONSE;
                    if (accepted && atomic_load(&bridge_active) &&
                        !strcmp(str(accepted, "phase"), "PRECHECK"))
                        err = execute(session, accepted);
                    if (err != ESP_OK)
                        event(cancelled || atomic_load(&stop_requested) ||
                              !atomic_load(&bridge_active) ? "CANCELLED"
                                                                        : "FAILED",
                              0, err);
                    cJSON_Delete(accepted);
                    cJSON_Delete(r);
                    break;
                }
                cJSON_Delete(r);
            } else if (last_http_status == 401 || last_http_status == 404 ||
                       last_http_status == 410) {
                set_state("ENDED", 0, ESP_ERR_INVALID_STATE);
                break;
            } else {
                backoff = backoff < 30 ? backoff * 2 : 60;
            }
        }
        if (session[0] && !atomic_load(&bridge_active)) continue;
        unsigned wait_seconds =
            retry_after_seconds > backoff ? retry_after_seconds : backoff;
        unsigned remaining_ms = wait_seconds * 1000 + esp_random() % 1000;
        while (remaining_ms && !atomic_load(&stop_requested)) {
            if (session[0] && !atomic_load(&bridge_active)) break;
            unsigned n = remaining_ms > 250 ? 250 : remaining_ms;
            vTaskDelay(pdMS_TO_TICKS(n));
            remaining_ms -= n;
        }
    }
    if (atomic_load(&stop_requested)) {
        if (session[0])
            event("CANCELLED", 0, ESP_ERR_INVALID_STATE);
        else
            set_state("CANCELLED", 0, ESP_OK);
    }
    memset(session, 0, sizeof(session));
    memset(token, 0, sizeof(token));
    atomic_store(&bridge_running, false);
    vTaskDelete(NULL);
}

void iris_bridge_stop(void)
{
    atomic_store(&stop_requested, true);
}

void iris_bridge_set_active(bool active)
{
    atomic_store(&bridge_active, active);
}

bool iris_bridge_is_running(void)
{
    return atomic_load(&bridge_running);
}

esp_err_t iris_bridge_start(const iris_bridge_config_t *config)
{
    bool expected = false;
    if (!atomic_compare_exchange_strong(&bridge_running, &expected, true))
        return ESP_ERR_INVALID_STATE;
    esp_err_t err = ESP_ERR_NOT_SUPPORTED;
#if !CONFIG_ESP_IRIS_SYSTEM_UPDATE || !CONFIG_IRIS_FACTORY_SYSTEM_UPDATE_BACKEND ||    \
    !CONFIG_SPIRAM_XIP_FROM_PSRAM
    goto fail;
#endif
    err = ESP_ERR_INVALID_ARG;
    if (!config || !config->server_url || !config->board_id || !config->device_id)
        goto fail;
    if (!*config->server_url || !*config->board_id) {
        set_state("NOT_CONFIGURED", 0, ESP_ERR_INVALID_STATE);
        atomic_store(&bridge_running, false);
        return ESP_ERR_INVALID_STATE;
    }
    if (strncmp(config->server_url, "https://", 8) || !config->server_url[8] ||
        strpbrk(config->server_url + 8, "/?#@ \t\r\n") ||
        strlen(config->server_url) >= sizeof(server_url) ||
        strlen(config->board_id) >= sizeof(board_id) || strlen(config->device_id) != 32)
        goto fail;
    err = ESP_ERR_NOT_SUPPORTED;
    if (!CONFIG_IDF_TARGET_ESP32S31 || CONFIG_PARTITION_TABLE_OFFSET != 0x8000 ||
        CONFIG_BOOTLOADER_OFFSET_IN_FLASH != 0x2000 || esp_secure_boot_enabled() ||
        esp_efuse_is_flash_encryption_enabled())
        goto fail;
    const esp_partition_t *running = esp_ota_get_running_partition();
    if (!running || running->subtype != ESP_PARTITION_SUBTYPE_APP_FACTORY)
        goto fail;
    uint8_t bytes[16], address[6];
    if (!boot_id[0]) {
        esp_fill_random(bytes, sizeof(bytes));
        hex(bytes, sizeof(bytes), boot_id);
    }
    err = ESP_FAIL;
    if (esp_read_mac(address, ESP_MAC_EFUSE_FACTORY) != ESP_OK ||
        psa_crypto_init() != PSA_SUCCESS)
        goto fail;
    snprintf(mac, sizeof(mac), "%02x:%02x:%02x:%02x:%02x:%02x", address[0], address[1],
             address[2], address[3], address[4], address[5]);
    strlcpy(server_url, config->server_url, sizeof(server_url));
    strlcpy(board_id, config->board_id, sizeof(board_id));
    strlcpy(device_id, config->device_id, sizeof(device_id));
    cfg = *config;
    cfg.server_url = server_url;
    cfg.board_id = board_id;
    cfg.device_id = device_id;
    taskENTER_CRITICAL(&snapshot_lock);
    memset(&snapshot, 0, sizeof(snapshot));
    strlcpy(snapshot.server_url, server_url, sizeof(snapshot.server_url));
    strlcpy(snapshot.state, "WAITING_NETWORK", sizeof(snapshot.state));
    taskEXIT_CRITICAL(&snapshot_lock);
    cancelled = false;
    atomic_store(&bridge_active, !config->prefetch_only);
    atomic_store(&stop_requested, false);
    if (xTaskCreate(run, "iris_bridge", 24576, NULL, 4, NULL) == pdPASS)
        return ESP_OK;
    err = ESP_ERR_NO_MEM;
fail:
    set_state("FAILED", 0, err);
    atomic_store(&bridge_running, false);
    return err;
}
