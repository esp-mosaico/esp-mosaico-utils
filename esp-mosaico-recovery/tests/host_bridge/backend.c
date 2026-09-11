#include "backend_sdk.h"
#include <assert.h>
#include BACKEND_SOURCE

int64_t mock_time;
bool mock_network, mock_stop_on_delay;
int mock_create_fail, mock_alloc_fail, mock_commit_error, mock_writes, mock_commits,
    mock_reserved, mock_abort;
void (*mock_worker)(void *);
esp_partition_t mock_factory = {
    .address = 0x20000, .size = 0x1c0000, .label = "factory"};
void *esp_flash_default_chip;
static uint8_t flash[0x1000000];
static int erased, persisted, corrupt_readback;
static uint32_t last_write;
static const esp_partition_t *boot;
void vTaskDelay(unsigned ms)
{
    (void)ms;
}
void vTaskDelete(void *task)
{
    (void)task;
}
void esp_restart(void)
{
    assert(false);
}
esp_err_t esp_flash_read(void *chip, void *buf, uint32_t offset, size_t size)
{
    (void)chip;
    assert(offset + size <= sizeof(flash));
    memcpy(buf, flash + offset, size);
    if (corrupt_readback && offset >= 0x200000 && size)
        ((uint8_t *)buf)[0] ^= 1;
    return 0;
}
esp_err_t esp_partition_table_verify(const esp_partition_info_t *entries, bool checksum,
                                     int *count)
{
    (void)checksum;
    *count = 0;
    while (entries[*count].magic == ESP_PARTITION_MAGIC)
        (*count)++;
    return 0;
}
esp_err_t esp_partition_erase_range(const esp_partition_t *p, uint32_t offset,
                                    size_t size)
{
    assert(p->address >= 0x200000);
    assert(offset + size <= p->size);
    memset(flash + p->address + offset, 0xff, size);
    erased++;
    return 0;
}
esp_err_t esp_partition_write(const esp_partition_t *p, uint32_t offset,
                              const void *data, size_t size)
{
    assert(offset + size <= p->size);
    memcpy(flash + p->address + offset, data, size);
    mock_writes++;
    return 0;
}
esp_err_t esp_flash_set_dangerous_write_protection(void *chip, bool enabled)
{
    (void)chip;
    (void)enabled;
    return 0;
}
esp_err_t esp_flash_erase_region(void *chip, uint32_t offset, size_t size)
{
    (void)chip;
    assert(boot == &mock_factory);
    memset(flash + offset, 0xff, size);
    erased++;
    return 0;
}
esp_err_t esp_flash_write(void *chip, const void *data, uint32_t offset, size_t size)
{
    (void)chip;
    memcpy(flash + offset, data, size);
    last_write = offset;
    mock_writes++;
    return 0;
}
esp_err_t esp_image_verify(int mode, const esp_partition_pos_t *pos,
                           esp_image_metadata_t *metadata)
{
    (void)mode;
    (void)pos;
    (void)metadata;
    return 0;
}
esp_err_t esp_image_verify_bootloader(uint32_t *size)
{
    *size = 0;
    return 0;
}
const esp_partition_t *esp_partition_find_first(int type, int subtype,
                                                const char *label)
{
    (void)type;
    (void)subtype;
    return !strcmp(label, "factory") ? &mock_factory : NULL;
}
const esp_partition_t *esp_ota_get_boot_partition(void)
{
    return boot;
}
esp_err_t esp_ota_set_boot_partition(const esp_partition_t *p)
{
    boot = p;
    return 0;
}
esp_err_t esp_iris_crash_loop_reset(void)
{
    return 0;
}
esp_err_t esp_iris_mark_planned_restart(void)
{
    return 0;
}
esp_err_t factory_system_metadata_store_last_result(const uint8_t *op, esp_err_t result)
{
    (void)op;
    (void)result;
    persisted++;
    return mock_commit_error;
}
esp_err_t
esp_iris_system_update_register(const esp_iris_system_update_backend_t *backend)
{
    (void)backend;
    return 0;
}
esp_err_t factory_system_update_nand_register(void)
{
    return 0;
}
static uint8_t op[16] = {1};
static void setup(void)
{
    update_state_reset();
    update_owner_release();
    memset(flash, 0xff, sizeof(flash));
    erased = mock_writes = persisted = corrupt_readback = mock_alloc_fail =
        mock_commit_error = 0;
    boot = NULL;
    esp_partition_info_t *entries = (void *)(flash + 0x8000);
    for (size_t i = 0; i < 5; i++) {
        const immutable_partition_contract_t *c = &s_immutable_partitions[i];
        entries[i] = (esp_partition_info_t){.magic = ESP_PARTITION_MAGIC,
                                            .type = c->type,
                                            .subtype = c->subtype,
                                            .pos = {c->offset, c->size}};
        strncpy(entries[i].label, c->label, 16);
    }
    entries[5] = (esp_partition_info_t){.magic = ESP_PARTITION_MAGIC,
                                        .type = ESP_PARTITION_TYPE_DATA,
                                        .subtype = 0x82,
                                        .pos = {0x200000, 0x10000},
                                        .label = "data"};
    entries[6] = (esp_partition_info_t){.magic = ESP_PARTITION_MAGIC,
                                        .type = ESP_PARTITION_TYPE_APP,
                                        .subtype = 16,
                                        .pos = {0x210000, 0x100000},
                                        .label = "ota_0"};
}
static char *manifest(bool preserve, const char *kind, uint32_t offset, uint32_t size)
{
    uint8_t digest[32];
    char hash[65];
    hash_flash_region(0x8000, 4096, digest);
    for (int i = 0; i < 32; i++)
        sprintf(hash + 2 * i, "%02x", digest[i]);
    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "schema", FACTORY_SYSTEM_SCHEMA);
    cJSON *target = cJSON_AddObjectToObject(root, "target");
    cJSON_AddNumberToObject(target, "chip_id", 32);
    cJSON_AddNumberToObject(target, "flash_size", sizeof(flash));
    cJSON_AddStringToObject(root, "target_layout_sha256", hash);
    cJSON_AddBoolToObject(root, "preserve_layout", preserve);
    cJSON *items = cJSON_AddArrayToObject(root, "components"),
          *c = cJSON_CreateObject();
    cJSON_AddItemToArray(items, c);
    cJSON_AddNumberToObject(c, "id", 1);
    cJSON_AddStringToObject(c, "kind", kind);
    cJSON_AddNumberToObject(c, "target_offset", offset);
    cJSON_AddNumberToObject(c, "size", size);
    size_t written;
    psa_hash_compute(PSA_ALG_SHA_256, "data", 4, digest, 32, &written);
    for (int i = 0; i < 32; i++)
        sprintf(hash + 2 * i, "%02x", digest[i]);
    cJSON_AddStringToObject(c, "sha256", hash);
    cJSON_AddStringToObject(c, "file", "image.bin");
    char *json = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    return json;
}
static esp_err_t prepare(factory_system_update_owner_t owner, char *json)
{
    esp_err_t err =
        factory_system_update_source_prepare(owner, (uint8_t *)json, strlen(json), op);
    free(json);
    return err;
}
static uint8_t new_table[4096];
static char *layout_manifest(bool complete)
{
    memcpy(new_table, flash + 0x8000, 4096);
    ((esp_partition_info_t *)new_table)[5].pos.offset = 0x310000;
    char *json = manifest(false, "partition_table", 0x8000, 4096);
    cJSON *root = cJSON_Parse(json);
    free(json);
    uint8_t digest[32];
    char hash[65];
    hash_memory(new_table, 4096, digest);
    for (int i = 0; i < 32; i++)
        sprintf(hash + 2 * i, "%02x", digest[i]);
    cJSON_ReplaceItemInObject(root, "target_layout_sha256", cJSON_CreateString(hash));
    cJSON *items = cJSON_GetObjectItem(root, "components");
    cJSON_ReplaceItemInObject(cJSON_GetArrayItem(items, 0), "sha256",
                              cJSON_CreateString(hash));
    for (int i = 0; i < (complete ? 2 : 1); i++) {
        char *extra =
            manifest(false, i ? "application" : "data", i ? 0x210000 : 0x310000, 4);
        cJSON *other = cJSON_Parse(extra);
        free(extra);
        cJSON *c =
            cJSON_DetachItemFromArray(cJSON_GetObjectItem(other, "components"), 0);
        cJSON_ReplaceItemInObject(c, "id", cJSON_CreateNumber(i + 2));
        cJSON_ReplaceItemInObject(c, "file",
                                  cJSON_CreateString(i ? "app.bin" : "data.bin"));
        cJSON_AddItemToArray(items, c);
        cJSON_Delete(other);
    }
    json = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    return json;
}

int main(void)
{
    setup();
    assert(factory_system_update_source_reserve(FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE,
                                                op) == 0);
    assert(factory_system_update_source_reserve(FACTORY_SYSTEM_UPDATE_OWNER_NAND, op) ==
           ESP_ERR_INVALID_STATE);
    factory_system_update_source_abort(FACTORY_SYSTEM_UPDATE_OWNER_NAND, op, ESP_FAIL);
    assert(update_owner_is(FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE));
    factory_system_update_source_abort(FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE, op,
                                       ESP_FAIL);
    assert(update_owner_is(FACTORY_SYSTEM_UPDATE_OWNER_NONE));
    /* JSON alone cannot opt USB/NAND into the remote policy. */
    setup();
    assert(prepare(FACTORY_SYSTEM_UPDATE_OWNER_NAND,
                   manifest(true, "data", 0x200000, 4)) != 0);
    assert(!erased);
    setup();
    char *json = manifest(true, "data", 0x200000, 4);
    cJSON *root = cJSON_Parse(json);
    free(json);
    cJSON_AddBoolToObject(root, "remote_bridge", true);
    json = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    assert(prepare(FACTORY_SYSTEM_UPDATE_OWNER_NAND, json) != 0);
    assert(!erased);
    setup();
    assert(prepare(FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE,
                   manifest(true, "data", 0xc000, 4)) != 0);
    assert(!erased);
    setup();
    assert(prepare(FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE,
                   manifest(true, "application", 0x200000, 4)) != 0);
    assert(!erased);
    /* Actual source table hash and protected prefix are independently checked. */
    setup();
    json = manifest(true, "data", 0x200000, 4);
    flash[0x8000 + 12] = 'X';
    assert(prepare(FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE, json) != 0);
    assert(!erased);
    setup();
    ((esp_partition_info_t *)(flash + 0x8000))[0].pos.offset = 0xa000;
    assert(prepare(FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE,
                   manifest(true, "data", 0x200000, 4)) != 0);
    assert(!erased);
    /* Preserve-layout data update writes only selected partition, verifies readback. */
    setup();
    assert(prepare(FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE,
                   manifest(true, "data", 0x200000, 4)) == 0);
    esp_iris_system_update_component_t c = s_update.plan[0].descriptor;
    assert(factory_system_update_source_begin_component(
               FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE, &c) == 0);
    assert(factory_system_update_source_write_component(
               FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE, &c, 0, (uint8_t *)"data", 4) == 0);
    assert(factory_system_update_source_end_component(
               FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE, &c, c.sha256) == 0);
    assert(factory_system_update_source_commit(FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE,
                                               op) == 0);
    assert(erased == 1 && mock_writes == 1 && boot == &mock_factory && persisted == 1);
    assert(
        factory_system_update_source_needs_restart(FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE));
    setup();
    assert(prepare(FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE,
                   manifest(true, "data", 0x200000, 4)) == 0);
    c = s_update.plan[0].descriptor;
    assert(begin_component(&c, NULL) == 0);
    assert(write_component(&c, 0, (uint8_t *)"data", 4, NULL) == 0);
    corrupt_readback = 1;
    assert(end_component(&c, c.sha256, NULL) == ESP_ERR_INVALID_CRC);
    assert(commit_update(op, NULL) != 0);
    /* Factory staging failure cannot erase the running image. */
    setup();
    assert(prepare(FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE,
                   manifest(true, "recovery", 0x20000, 0x1c0000)) == 0);
    mock_alloc_fail = 1;
    c = s_update.plan[0].descriptor;
    assert(begin_component(&c, NULL) == ESP_ERR_NO_MEM);
    assert(!erased && !mock_writes);
    /* A malformed staged Recovery is rejected before dangerous writes. */
    mock_alloc_fail = 0;
    assert(begin_component(&c, NULL) == 0);
    memset(s_update.recovery_image, 0, 0x1c0000);
    s_update.received = 0x1c0000;
    assert(end_component(&c, c.sha256, NULL) == ESP_ERR_IMAGE_INVALID);
    assert(!erased && !mock_writes);
    /* Layout requires every mutable target, then commits its table last. */
    setup();
    assert(prepare(FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE, layout_manifest(false)) == 0);
    c = s_update.plan[0].descriptor;
    assert(begin_component(&c, NULL) == 0);
    assert(write_component(&c, 0, new_table, 4096, NULL) == 0);
    assert(end_component(&c, c.sha256, NULL) != 0);
    assert(!erased);
    setup();
    assert(prepare(FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE, layout_manifest(true)) == 0);
    for (size_t i = 0; i < 3; i++) {
        c = s_update.plan[i].descriptor;
        assert(begin_component(&c, NULL) == 0);
        const uint8_t *data = i ? (const uint8_t *)"data" : new_table;
        assert(write_component(&c, 0, data, c.size, NULL) == 0);
        assert(end_component(&c, c.sha256, NULL) == 0);
        assert(!memcmp(flash + 0x8000 + 5 * 32 + 4, "\0\0\x20\0", 4));
    }
    assert(commit_update(op, NULL) == 0);
    assert(last_write == 0x8000);
    assert(!memcmp(flash + 0x8000, new_table, 4096));
    /* A complete Recovery image validates in PSRAM before its single copy commit. */
    setup();
    uint8_t *image = malloc(0x1c0000);
    memset(image, 0xff, 0x1c0000);
    esp_image_header_t header = {
        .magic = ESP_IMAGE_HEADER_MAGIC, .segment_count = 1, .chip_id = 32};
    memcpy(image, &header, sizeof(header));
    esp_image_segment_header_t segment = {.data_len = 4};
    memcpy(image + sizeof(header), &segment, sizeof(segment));
    memcpy(image + sizeof(header) + sizeof(segment), "data", 4);
    size_t end = (sizeof(header) + sizeof(segment) + 4 + 1 + 15) & ~(size_t)15;
    image[end - 1] = 0xef ^ 'd' ^ 'a' ^ 't' ^ 'a';
    uint8_t sha[32];
    hash_memory(image, 0x1c0000, sha);
    json = manifest(true, "recovery", 0x20000, 0x1c0000);
    root = cJSON_Parse(json);
    free(json);
    char hash[65];
    for (int i = 0; i < 32; i++)
        sprintf(hash + 2 * i, "%02x", sha[i]);
    cJSON_ReplaceItemInObject(
        cJSON_GetArrayItem(cJSON_GetObjectItem(root, "components"), 0), "sha256",
        cJSON_CreateString(hash));
    json = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    assert(prepare(FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE, json) == 0);
    c = s_update.plan[0].descriptor;
    assert(begin_component(&c, NULL) == 0);
    assert(write_component(&c, 0, image, c.size, NULL) == 0);
    assert(end_component(&c, c.sha256, NULL) == 0);
    assert(!erased);
    mock_commit_error = ESP_FAIL;
    assert(commit_update(op, NULL) == ESP_FAIL);
    assert(
        factory_system_update_source_needs_restart(FACTORY_SYSTEM_UPDATE_OWNER_BRIDGE));
    assert(last_write == 0x20000 && !memcmp(flash + 0x20000, image, 0x1c0000));
    free(image);
    puts("Recovery backend ownership, layout, readback and factory gates passed");
}
