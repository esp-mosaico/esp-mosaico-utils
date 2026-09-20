#include "sdk.h"
#include <assert.h>
#include <setjmp.h>
#include BRIDGE_SOURCE

#define TEST_PAIRING_EXPIRY "2026-09-11T20:10:00.123456789+08:00"

int64_t mock_time;
bool mock_network, mock_stop_on_delay;
int mock_create_fail, mock_alloc_fail, mock_commit_error, mock_writes, mock_commits,
    mock_reserved, mock_abort;
void (*mock_worker)(void *);
esp_partition_t mock_factory = {
    .address = 0x20000, .size = 0x1c0000, .label = "factory"};
static esp_partition_t app = {
    .address = 0x210000, .size = 0x100000, .subtype = 16, .label = "ota_0"};
static jmp_buf worker_exit;
static int restart_count, requests, allocation_count, mock_backend_alloc_fail;
static esp_iris_system_update_component_t descriptor;
static int replies_count, reply_index, test_case;
static int pairing_snapshots;
static bool expire_on_delay;
static int activate_after_delays;
static bool pause_on_poll;
static struct reply {
    const char *path, *body;
    int status;
    bool stop;
} replies[16];
struct mock_http {
    struct reply *reply;
    size_t offset;
};

void vTaskDelay(unsigned ms)
{
    mock_time += (int64_t)ms * 1000;
    if (activate_after_delays && --activate_after_delays == 0) {
        assert(requests == 1); /* No background polling or re-registration. */
        iris_bridge_set_active(true);
    }
    if (expire_on_delay) {
        mock_time += 600000000;
        expire_on_delay = false;
    }
    if (mock_stop_on_delay)
        iris_bridge_stop();
    assert(mock_time < 1000000000LL);
}
void vTaskDelete(void *arg)
{
    (void)arg;
    longjmp(worker_exit, 1);
}
void esp_restart(void)
{
    restart_count++;
    longjmp(worker_exit, 2);
}
esp_err_t esp_ota_set_boot_partition(const esp_partition_t *p)
{
    assert(p);
    return 0;
}
const esp_partition_t *esp_partition_find_first(int type, int subtype,
                                                const char *label)
{
    (void)type;
    (void)subtype;
    return !strcmp(label, "factory") ? &mock_factory : &app;
}
esp_http_client_handle_t esp_http_client_init(const esp_http_client_config_t *config)
{
    assert(config->disable_auto_redirect);
    assert(!strncmp(config->url, "https://flash.example.com/", 26));
    if (reply_index >= replies_count)
        fprintf(stderr, "case %d unexpected URL %s\n", test_case, config->url);
    assert(reply_index < replies_count);
    struct reply *r = &replies[reply_index++];
    assert(strstr(config->url, r->path));
    if (strstr(config->url, "/poll")) {
        iris_bridge_snapshot_t pairing;
        iris_bridge_get_snapshot(&pairing);
        if (!strcmp(pairing.state, "PAIRING")) {
            assert(!strcmp(pairing.expires_at, TEST_PAIRING_EXPIRY));
            pairing_snapshots++;
        }
    }
    struct mock_http *h = calloc(1, sizeof(*h));
    h->reply = r;
    requests++;
    return h;
}
esp_err_t esp_http_client_open(esp_http_client_handle_t h, size_t length)
{
    (void)length;
    return h->reply->status ? 0 : ESP_FAIL;
}
int esp_http_client_fetch_headers(esp_http_client_handle_t h)
{
    return strlen(h->reply->body);
}
int esp_http_client_get_status_code(esp_http_client_handle_t h)
{
    return h->reply->status;
}
int esp_http_client_read(esp_http_client_handle_t h, char *out, size_t n)
{
    size_t left = strlen(h->reply->body) - h->offset;
    if (n > left)
        n = left;
    if (n > 4096)
        n = 4096;
    memcpy(out, h->reply->body + h->offset, n);
    h->offset += n;
    if (h->reply->stop)
        iris_bridge_stop();
    if (pause_on_poll && strstr(h->reply->path, "/poll")) {
        iris_bridge_set_active(false);
        pause_on_poll = false;
        expire_on_delay = true;
    }
    return n;
}
int esp_http_client_write(esp_http_client_handle_t h, const char *data, size_t n)
{
    (void)h;
    (void)data;
    return n;
}
bool esp_http_client_is_complete_data_received(esp_http_client_handle_t h)
{
    return h->offset == strlen(h->reply->body);
}
void esp_http_client_set_header(esp_http_client_handle_t h, const char *key,
                                const char *value)
{
    (void)h;
    (void)key;
    (void)value;
}
void esp_http_client_set_method(esp_http_client_handle_t h, int method)
{
    (void)h;
    (void)method;
}
void esp_http_client_close(esp_http_client_handle_t h)
{
    (void)h;
}
void esp_http_client_cleanup(esp_http_client_handle_t h)
{
    free(h);
}
esp_err_t factory_system_metadata_load_last_result(factory_sysmeta_record_t *out)
{
    (void)out;
    return ESP_ERR_NOT_FOUND;
}
esp_err_t factory_system_update_source_reserve(factory_system_update_owner_t owner,
                                               const uint8_t *op)
{
    (void)owner;
    (void)op;
    if (mock_reserved)
        return ESP_ERR_INVALID_STATE;
    mock_reserved = 1;
    return 0;
}
esp_err_t factory_system_update_source_prepare(factory_system_update_owner_t owner,
                                               const uint8_t *json, size_t size,
                                               const uint8_t *op)
{
    (void)owner;
    (void)size;
    (void)op;
    cJSON *root = cJSON_Parse((const char *)json);
    assert(root);
    assert(!cJSON_GetObjectItem(root, "remote_bridge"));
    const cJSON *c = cJSON_GetArrayItem(cJSON_GetObjectItem(root, "components"), 0);
    descriptor.size = num(c, "size");
    descriptor.id = 1;
    descriptor.target_offset = num(c, "target_offset");
    descriptor.kind = !strcmp(str(c, "kind"), "recovery")
                          ? ESP_IRIS_SYSTEM_UPDATE_COMPONENT_RECOVERY
                          : ESP_IRIS_SYSTEM_UPDATE_COMPONENT_DATA;
    const char *sha = str(c, "sha256");
    for (int i = 0; i < 32; i++) {
        unsigned b;
        sscanf(sha + 2 * i, "%2x", &b);
        descriptor.sha256[i] = b;
    }
    cJSON_Delete(root);
    return 0;
}
size_t factory_system_update_source_component_count(factory_system_update_owner_t owner)
{
    (void)owner;
    return 1;
}
esp_err_t factory_system_update_source_component(factory_system_update_owner_t owner,
                                                 size_t index,
                                                 esp_iris_system_update_component_t *c,
                                                 char *file)
{
    (void)owner;
    (void)index;
    *c = descriptor;
    strcpy(file, "image");
    return 0;
}
esp_err_t factory_system_update_source_begin_component(
    factory_system_update_owner_t owner, const esp_iris_system_update_component_t *c)
{
    (void)owner;
    (void)c;
    allocation_count++;
    return mock_backend_alloc_fail ? ESP_ERR_NO_MEM : 0;
}
esp_err_t factory_system_update_source_write_component(
    factory_system_update_owner_t owner, const esp_iris_system_update_component_t *c,
    uint32_t offset, const uint8_t *data, size_t n)
{
    (void)owner;
    (void)c;
    (void)offset;
    (void)data;
    (void)n;
    mock_writes++;
    return 0;
}
esp_err_t
factory_system_update_source_end_component(factory_system_update_owner_t owner,
                                           const esp_iris_system_update_component_t *c,
                                           const uint8_t *sha)
{
    (void)owner;
    return memcmp(c->sha256, sha, 32) ? ESP_ERR_INVALID_CRC : 0;
}
esp_err_t factory_system_update_source_commit(factory_system_update_owner_t owner,
                                              const uint8_t *op)
{
    (void)owner;
    (void)op;
    mock_commits++;
    return mock_commit_error;
}
bool factory_system_update_source_needs_restart(factory_system_update_owner_t owner)
{
    (void)owner;
    return mock_commits > 0;
}
void factory_system_update_source_abort(factory_system_update_owner_t owner,
                                        const uint8_t *op, esp_err_t err)
{
    (void)owner;
    (void)op;
    (void)err;
    mock_reserved = 0;
    mock_abort++;
}

static uint8_t pending_boot[128];
static size_t pending_size;
static unsigned erased_boot_records;
esp_err_t nvs_open_from_partition(const char *partition, const char *ns, int mode,
                                  nvs_handle_t *n)
{
    assert(!strcmp(partition, "sysmeta") && !strcmp(ns, "iris_bridge"));
    (void)mode;
    *n = 1;
    return ESP_OK;
}
esp_err_t nvs_get_blob(nvs_handle_t n, const char *key, void *out, size_t *size)
{
    (void)n;
    (void)key;
    if (!pending_size)
        return ESP_ERR_NVS_NOT_FOUND;
    if (*size < pending_size)
        return ESP_ERR_INVALID_SIZE;
    memcpy(out, pending_boot, pending_size);
    *size = pending_size;
    return ESP_OK;
}
esp_err_t nvs_set_blob(nvs_handle_t n, const char *key, const void *out, size_t size)
{
    (void)n;
    (void)key;
    assert(size <= sizeof(pending_boot));
    memcpy(pending_boot, out, size);
    pending_size = size;
    return ESP_OK;
}
esp_err_t nvs_erase_key(nvs_handle_t n, const char *key)
{
    (void)n;
    (void)key;
    pending_size = 0;
    erased_boot_records++;
    return ESP_OK;
}
esp_err_t nvs_commit(nvs_handle_t n)
{
    (void)n;
    return ESP_OK;
}
void nvs_close(nvs_handle_t n)
{
    (void)n;
}

static bool ready(void)
{
    return mock_network;
}
static iris_bridge_config_t config = {.server_url = "https://flash.example.com",
                                      .board_id = "test-s31",
                                      .device_id = "12345678901234567890123456789012",
                                      .enable_factory_update = true,
                                      .network_ready = ready};
static void reset(void)
{
    test_case++;
    expire_on_delay = false;
    activate_after_delays = 0;
    pause_on_poll = false;
    atomic_store(&bridge_active, true);
    atomic_store(&bridge_running, false);
    atomic_store(&stop_requested, false);
    memset(session, 0, sizeof(session));
    memset(token, 0, sizeof(token));
    mock_time = 0;
    mock_network = true;
    mock_stop_on_delay = false;
    mock_create_fail = 0;
    mock_alloc_fail = 0;
    mock_commit_error = 0;
    mock_writes = 0;
    mock_commits = 0;
    mock_reserved = 0;
    mock_abort = 0;
    restart_count = 0;
    requests = 0;
    allocation_count = 0;
    mock_backend_alloc_fail = 0;
    replies_count = 0;
    reply_index = 0;
    cancelled = false;
    last_cancel_check = 0;
    set_state("IDLE", 0, 0);
}
static void reply(const char *path, int status, const char *body, bool stop)
{
    replies[replies_count++] = (struct reply){path, body, status, stop};
}
static void run_worker(void)
{
    if (!setjmp(worker_exit))
        mock_worker(NULL);
}
static const char *registration =
    "{\"session_id\":\"12345678901234567890123456789012\",\"auth_token\":\"SECRET\","
    "\"device_code\":\"ABCDE-12345\",\"expires_at\":\"" TEST_PAIRING_EXPIRY "\"}";
static cJSON *plan(const char *mode)
{
    cJSON *p = cJSON_CreateObject();
    char hash[65];
    assert(flash_hash(0x8000, 4096, hash));
    cJSON_AddStringToObject(p, "mode", mode);
    cJSON_AddStringToObject(p, "source_table_sha256", hash);
    cJSON_AddStringToObject(p, "target_table_sha256", hash);
    cJSON_AddStringToObject(p, "boot_partition", "factory");
    cJSON *images = cJSON_AddArrayToObject(p, "images"), *im = cJSON_CreateObject();
    cJSON_AddItemToArray(images, im);
    cJSON_AddStringToObject(im, "partition",
                            !strcmp(mode, "factory") ? "factory" : "data");
    cJSON_AddStringToObject(im, "upload_id", "image");
    cJSON_AddNumberToObject(im, "offset", 0x210000);
    cJSON_AddNumberToObject(im, "size", 4);
    uint8_t digest_bytes[32];
    digest("data", 4, digest_bytes);
    hex(digest_bytes, 32, hash);
    cJSON_AddStringToObject(im, "sha256", hash);
    cJSON *m = cJSON_AddObjectToObject(p, "factory_manifest");
    cJSON_AddStringToObject(m, "board_id", "test-s31");
    cJSON_AddStringToObject(m, "profile_id", "iris-s31-layout-v1");
    cJSON_AddStringToObject(m, "recovery_version", "3.0");
    cJSON_AddNumberToObject(m, "protocol_version", 1);
    return p;
}

int main(void)
{
    iris_bridge_snapshot_t out;
    reset();
    iris_bridge_config_t empty = config;
    empty.server_url = "";
    assert(iris_bridge_start(&empty) != 0);
    iris_bridge_get_snapshot(&out);
    assert(!strcmp(out.state, "NOT_CONFIGURED"));
    assert(!requests);
    reset();
    mock_network = false;
    assert(iris_bridge_start(&config) == 0);
    assert(iris_bridge_start(&config) == ESP_ERR_INVALID_STATE);
    iris_bridge_get_snapshot(&out);
    assert(!strcmp(out.state, "WAITING_NETWORK"));
    mock_stop_on_delay = true;
    run_worker();
    assert(!requests);
    assert(!iris_bridge_is_running());
    iris_bridge_get_snapshot(&out);
    assert(!strcmp(out.state, "CANCELLED"));
    reset();
    mock_create_fail = 1;
    assert(iris_bridge_start(&config) == ESP_ERR_NO_MEM);
    assert(!iris_bridge_is_running());
    reset();
    reply("device-sessions", 201, registration, false);
    reply("/poll", 410, "{}", false);
    assert(iris_bridge_start(&config) == 0);
    run_worker();
    iris_bridge_get_snapshot(&out);
    assert(!out.running && !out.code[0] && !token[0]);
    assert(!strcmp(out.state, "ENDED"));
    assert(requests == 2);
    assert(pairing_snapshots > 0);
    /* Re-entry after completed cleanup allocates exactly one new session. */
    reply("device-sessions", 201, registration, false);
    reply("/poll", 401, "{}", false);
    assert(iris_bridge_start(&config) == 0);
    run_worker();
    assert(requests == 4);
    reset();
    reply("device-sessions", 201, registration, false);
    expire_on_delay = true;
    iris_bridge_config_t background = config;
    background.prefetch_only = true;
    assert(iris_bridge_start(&background) == 0);
    run_worker();
    iris_bridge_get_snapshot(&out);
    assert(!strcmp(out.state, "EXPIRED"));
    assert(!out.code[0] && requests == 1);
    /* Opening a prefetched session enables polling, without another POST. */
    reset();
    reply("device-sessions", 201, registration, false);
    reply("/poll", 410, "{}", false);
    activate_after_delays = 2;
    assert(iris_bridge_start(&background) == 0);
    run_worker();
    assert(requests == 2 && !mock_writes && !mock_commits);
    /* A visible expired code renews immediately; the new session is polled. */
    reset();
    reply("device-sessions", 201, registration, false);
    reply("device-sessions", 201, registration, false);
    reply("/poll", 410, "{}", false);
    expire_on_delay = true;
    assert(iris_bridge_start(&config) == 0);
    run_worker();
    assert(requests == 3);
    /* Leaving during /poll must not process its queued update or inventory. */
    reset();
    reply("device-sessions", 201, registration, false);
    reply("/poll", 200, "{\"inventory_required\":true,\"flash\":{\"phase\":\"QUEUED\"}}", false);
    pause_on_poll = true;
    assert(iris_bridge_start(&config) == 0);
    run_worker();
    assert(requests == 2 && !mock_reserved && !mock_writes && !mock_commits);
    reset();
    for (int i = 0; i < 3; ++i) reply("device-sessions", 503, "{}", false);
    assert(iris_bridge_start(&background) == 0);
    run_worker();
    iris_bridge_get_snapshot(&out);
    assert(requests == 3 && !out.running && !strcmp(out.state, "FAILED"));
    reset();
    reply("device-sessions", 201, registration, true);
    reply("/progress", 200, "{}", false);
    assert(iris_bridge_start(&config) == 0);
    run_worker();
    assert(!token[0]);
    iris_bridge_get_snapshot(&out);
    assert(!strcmp(out.state, "CANCELLED"));
    reset();
    assert(iris_bridge_start(&config) == 0);
    atomic_store(&bridge_running, false);
    cJSON *p = plan("factory");
    mock_alloc_fail = 1;
    assert(execute("12345678901234567890123456789012", p) == ESP_ERR_NO_MEM);
    assert(!mock_reserved && !mock_writes && !mock_commits);
    cJSON_Delete(p);
    reset();
    p = plan("factory");
    cJSON_ReplaceItemInObject(cJSON_GetObjectItem(p, "factory_manifest"), "board_id",
                              cJSON_CreateString("wrong"));
    assert(execute("12345678901234567890123456789012", p) == ESP_ERR_INVALID_VERSION);
    assert(!mock_reserved && !requests);
    cJSON_Delete(p);
    reset();
    p = plan("partitions");
    mock_reserved = 1;
    assert(execute("12345678901234567890123456789012", p) == ESP_ERR_INVALID_STATE);
    assert(!requests && !mock_abort);
    cJSON_Delete(p);
    reset();
    p = plan("factory");
    reply("/files/", 200, "data", true);
    assert(execute("12345678901234567890123456789012", p) != 0);
    assert(!mock_writes && !mock_commits && !mock_reserved);
    cJSON_Delete(p);
    /* A rejected critical acknowledgement must never invoke commit. */
    reset();
    p = plan("partitions");
    reply("/progress", 200, "{}", false);
    reply("/files/", 200, "data", false);
    reply("/progress", 200, "{}", false);
    reply("/progress", 200, "{}", false);
    reply("/progress", 409, "{}", false);
    assert(execute("12345678901234567890123456789012", p) != 0);
    assert(mock_writes == 1 && !mock_commits && !mock_reserved);
    cJSON_Delete(p);
    /* Once authorized, local cancellation cannot interrupt critical commit. */
    reset();
    p = plan("partitions");
    reply("/progress", 200, "{}", false);
    reply("/files/", 200, "data", false);
    reply("/progress", 200, "{}", false);
    reply("/progress", 200, "{}", false);
    reply("/progress", 200, "{}", true);
    reply("/progress", 401, "{}", false);
    if (!setjmp(worker_exit))
        execute("12345678901234567890123456789012", p);
    assert(mock_commits == 1 && restart_count == 1 && !token[0]);
    cJSON_Delete(p);
    reset();
    p = plan("partitions");
    mock_commit_error = ESP_FAIL;
    reply("/progress", 200, "{}", false);
    reply("/files/", 200, "data", false);
    reply("/progress", 200, "{}", false);
    reply("/progress", 200, "{}", false);
    reply("/progress", 200, "{}", false);
    reply("/progress", 200, "{}", false);
    if (!setjmp(worker_exit))
        execute("12345678901234567890123456789012", p);
    assert(mock_commits == 1 && restart_count == 1);
    cJSON_Delete(p);
    reset();
    p = plan("partitions");
    cJSON_ReplaceItemInObject(p, "boot_partition", cJSON_CreateString("ota_0"));
    assert(save_boot(p) == ESP_OK && pending_size);
    if (!setjmp(worker_exit))
        iris_bridge_resume_boot();
    assert(restart_count == 1 && !pending_size && erased_boot_records == 1);
    assert(iris_bridge_resume_boot() == ESP_OK && restart_count == 1);
    assert(save_boot(p) == ESP_OK);
    ((boot_record_t *)pending_boot)->table_hash[0] ^= 1;
    assert(iris_bridge_resume_boot() == ESP_ERR_INVALID_VERSION && !pending_size);
    pending_size = sizeof(pending_boot);
    assert(iris_bridge_resume_boot() == ESP_ERR_INVALID_SIZE && !pending_size);
    cJSON_Delete(p);
    /* Original 3072-byte transport and FF-padded 4096-byte hash are distinct. */
    reset();
    char raw[3073];
    memset(raw, 0xff, 3072);
    raw[3072] = 0;
    p = plan("layout");
    char original_hash[65];
    uint8_t sha[32], table[4096];
    digest(raw, 3072, sha);
    hex(sha, 32, original_hash);
    cJSON_AddNumberToObject(p, "table_size", 3072);
    cJSON_AddStringToObject(p, "table_upload_id", "table");
    cJSON_AddStringToObject(p, "table_sha256", original_hash);
    reply("/files/", 200, raw, false);
    assert(get_table(p, table) == ESP_OK);
    for (size_t i = 0; i < sizeof(table); i++)
        assert(table[i] == 0xff);
    cJSON_ReplaceItemInObject(p, "table_sha256", cJSON_CreateString("bad"));
    reply("/files/", 200, raw, false);
    assert(get_table(p, table) != ESP_OK);
    reply("/files/", 410, "{}", false);
    assert(get_table(p, table) != ESP_OK);
    assert(!mock_writes && !mock_commits);
    cJSON_Delete(p);
    puts("Bridge worker, cancellation and transaction gates passed");
}
