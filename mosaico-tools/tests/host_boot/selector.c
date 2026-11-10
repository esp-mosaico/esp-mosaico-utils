#include "selector_sdk.h"
#include <assert.h>
#include SELECTOR_SOURCE

int main(void)
{
    stop_inherited_usb_dma();
    assert(!usb_resets); /* Cold boot: do not touch an unclocked controller. */
    usb_clock = true;
    stop_inherited_usb_dma();
    assert(usb_resets == 1 && !usb_clock);
    stop_inherited_usb_dma();
    assert(usb_resets == 1);
    bootloader_state_t bs = {
        .test = {MOSAICO_RECOVERY_ADDRESS, MOSAICO_RECOVERY_BYTES},
        .ota_info = {0x9000, MOSAICO_OTADATA_BYTES},
        .ota = {{0x210000, 0xdf0000}},
    };
    memset(bootstrap, 0xff, sizeof(bootstrap));
    memset(ota_entries, 0xff, sizeof(ota_entries));
    assert(select_partition_number(&bs) == 0); /* Blank otadata: native app flash. */
    app_header[0] = 0xff;
    assert(select_partition_number(&bs) == TEST_APP_INDEX); /* Deleted IDEA: erased header. */
    app_header[0] = ESP_IMAGE_HEADER_MAGIC;
    ota_entries[0] = (esp_ota_select_entry_t){1, ESP_OTA_IMG_VALID, true};
    key_error = ESP_OK;
    intent = MOSAICO_BOOT_INTENT_RECOVERY;
    assert(select_partition_number(&bs) == TEST_APP_INDEX);
    assert(select_partition_number(&bs) == TEST_APP_INDEX); /* Bootloader never consumes. */
    intent = MOSAICO_BOOT_INTENT_NONE;
    assert(select_partition_number(&bs) == 0);
    intent = 0xdeadbeef;
    assert(select_partition_number(&bs) == TEST_APP_INDEX);
    intent = 0;
    key_error = ESP_FAIL;
    assert(select_partition_number(&bs) == TEST_APP_INDEX);
    key_error = ESP_ERR_NVS_NOT_FOUND;
    nvs_error = ESP_FAIL;
    assert(select_partition_number(&bs) == TEST_APP_INDEX);
    nvs_error = ESP_OK;
    memcpy(bootstrap, MOSAICO_BOOTSTRAP_MARKER, sizeof(bootstrap));
    assert(select_partition_number(&bs) == TEST_APP_INDEX); /* recover, valid old app present. */
    memset(bootstrap, 0xff, sizeof(bootstrap));
    gpio_level = 0;
    assert(select_partition_number(&bs) == TEST_APP_INDEX);
    assert(held_us == CONFIG_FACTORY_RECOVERY_BOOT_DEBOUNCE_MS * 1000U);
    gpio_level = 1;
    held_us = 0;
    long_press_level = 0;
    long_press_release_us = (CONFIG_FACTORY_RECOVERY_LONG_PRESS_MS - 1) * 1000U;
    assert(select_partition_number(&bs) == 0); /* Released before the long press. */
    held_us = 0;
    long_press_release_us = 0;
    assert(select_partition_number(&bs) == TEST_APP_INDEX);
    assert(held_us == CONFIG_FACTORY_RECOVERY_LONG_PRESS_MS * 1000U);
    long_press_level = 1;
    ota_entries[0].ota_state = ESP_OTA_IMG_NEW;
    assert(select_partition_number(&bs) == 0); /* NEW still performs OTA verification. */
    assert(ota_entries[0].ota_state == ESP_OTA_IMG_PENDING_VERIFY);
    assert(select_partition_number(&bs) == TEST_APP_INDEX); /* Unconfirmed reset. */
    assert(ota_entries[0].ota_state == ESP_OTA_IMG_ABORTED);
    assert(select_partition_number(&bs) == TEST_APP_INDEX); /* No retry loop. */
    ota_entries[0].ota_state = ESP_OTA_IMG_INVALID;
    assert(select_partition_number(&bs) == TEST_APP_INDEX);
    ota_entries[1] = (esp_ota_select_entry_t){2, ESP_OTA_IMG_VALID, true};
    assert(select_partition_number(&bs) == 0); /* An older failed record does not block a valid one. */
    ota_entries[1].crc_valid = false;
    assert(select_partition_number(&bs) == TEST_APP_INDEX);
    ota_entries[1].crc_valid = true;
    ota_entries[1].ota_state = 42;
    assert(select_partition_number(&bs) == TEST_APP_INDEX);
    reset_reason = RESET_REASON_CORE_DEEP_SLEEP;
    assert(select_partition_number(&bs) == TEST_APP_INDEX);
    reset_reason = 0;
    ota_entries[1].ota_state = ESP_OTA_IMG_VALID;
    ota_error = ESP_FAIL;
    assert(select_partition_number(&bs) == TEST_APP_INDEX);
    ota_error = ESP_OK;
    selected = INVALID_INDEX;
    assert(select_partition_number(&bs) == TEST_APP_INDEX);
    bs.test.offset = 0; /* A wrong layout never grants a recovery boot target. */
    assert(select_partition_number(&bs) == INVALID_INDEX);
    table_ok = 0;
    assert(select_partition_number(&bs) == INVALID_INDEX);
    assert(writes == 0);
    return 0;
}
