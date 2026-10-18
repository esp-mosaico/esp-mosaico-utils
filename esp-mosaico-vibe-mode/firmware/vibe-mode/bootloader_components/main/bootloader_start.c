/*
 * SPDX-FileCopyrightText: 2015-2026 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <stdbool.h>
#include <inttypes.h>
#include <sys/reent.h>
#include <string.h>

#include "sdkconfig.h"
#include "esp_log.h"
#include "esp_efuse.h"
#include "esp_secure_boot.h"
#include "esp_rom_caps.h"
#include "esp_rom_gpio.h"
#include "esp_rom_sys.h"
#include "bootloader_init.h"
#include "bootloader_utility.h"
#include "bootloader_common.h"
#include "bootloader_flash_priv.h"
#include "esp_private/bootloader_flash_internal.h"
#include "hal/gpio_ll.h"
#include "hal/usb_utmi_ll.h"
#include "mosaico_boot_splash.h"
#include "soc/gpio_struct.h"
#include "soc/soc_caps.h"
#include "mosaico_boot_nvs.h"
#include "nvs.h"
#include "mosaico_recovery_contract.h"

ESP_LOG_ATTR_TAG(TAG, "boot");

static int select_partition_number(bootloader_state_t *bs);
static int selected_boot_partition(const bootloader_state_t *bs);

/* BEGIN MOSAICO_SINGLE_SLOT_POLICY
 * The ABI 2 product supports one normal application in a single physical OTA
 * slot. A previous VALID copy does not describe different application bytes.
 * CRC covers ota_seq only, so inspect terminal states before IDF filters them.
 */
static bool mosaico_single_slot_layout(const bootloader_state_t *bs)
{
    if (esp_efuse_is_flash_encryption_enabled() || esp_secure_boot_enabled() ||
        bs->app_count != 1 || bs->factory.offset != 0 || bs->factory.size != 0 ||
        bs->test.offset != MOSAICO_RECOVERY_ADDRESS ||
        bs->test.size != MOSAICO_RECOVERY_BYTES ||
        bs->ota_info.offset != 0x9000U || bs->ota_info.size != MOSAICO_OTADATA_BYTES ||
        bs->ota[0].offset != MOSAICO_APPLICATION_ADDRESS || bs->ota[0].size == 0 ||
        bs->ota[0].size % MOSAICO_FLASH_SECTOR_BYTES != 0 ||
        bs->ota[0].size > MOSAICO_FLASH_BYTES - MOSAICO_APPLICATION_ADDRESS) {
        return false;
    }
    for (unsigned i = 1; i < MAX_OTA_SLOTS; ++i) {
        if (bs->ota[i].offset != 0 || bs->ota[i].size != 0) return false;
    }
    return true;
}

static bool mosaico_ota_record_crc_valid(const esp_ota_select_entry_t *entry)
{
    return entry->ota_seq != UINT32_MAX &&
        entry->crc == bootloader_common_ota_select_crc(entry);
}

static bool mosaico_ota_state_known(uint32_t state)
{
    return state <= ESP_OTA_IMG_ABORTED || state == ESP_OTA_IMG_UNDEFINED;
}

static int mosaico_ota_sector_erased(uint32_t offset)
{
    uint32_t words[16];
    for (unsigned pos = 0; pos < MOSAICO_FLASH_SECTOR_BYTES; pos += sizeof(words)) {
        if (bootloader_flash_read(offset + pos, words, sizeof(words), true) != ESP_OK)
            return -1;
        for (unsigned i = 0; i < sizeof(words) / sizeof(words[0]); ++i) {
            if (words[i] != UINT32_MAX) return 0;
        }
    }
    return 1;
}

static bool mosaico_ota_keep_authority(const bootloader_state_t *bs, int authority)
{
    const uint32_t peer_offset = bs->ota_info.offset +
        (unsigned)(authority ^ 1) * MOSAICO_FLASH_SECTOR_BYTES;
    const int erased = mosaico_ota_sector_erased(peer_offset);
    if (erased < 0) return false;
    if (erased == 0) {
        /* Never erase the authority. A reset during peer erasure can only
         * leave the same authority or unusable metadata, both checked again. */
        if (bootloader_flash_erase_sector(peer_offset / MOSAICO_FLASH_SECTOR_BYTES) != ESP_OK)
            return false;
        if (mosaico_ota_sector_erased(peer_offset) != 1) return false;
    }
    return true;
}

static int mosaico_single_slot_selected(const bootloader_state_t *bs)
{
    esp_ota_select_entry_t entries[2];
    if (!mosaico_single_slot_layout(bs)) return INVALID_INDEX;
    if (bootloader_common_read_otadata(&bs->ota_info, entries) != ESP_OK)
        return TEST_APP_INDEX;

    bool present[2];
    int new_entry = -1;
    for (int i = 0; i < 2; ++i) {
        present[i] = mosaico_ota_record_crc_valid(&entries[i]);
        if (!present[i]) continue;
        if (entries[i].ota_seq == 0 || !mosaico_ota_state_known(entries[i].ota_state))
            return TEST_APP_INDEX;
        if (entries[i].ota_state == ESP_OTA_IMG_NEW) {
            /* Multiple NEW records cannot be produced by this normalized
             * single-slot history; imported ambiguity must not grant a trial. */
            if (new_entry != -1) return TEST_APP_INDEX;
            new_entry = i;
        }
    }

    int authority = present[0] ? 0 : (present[1] ? 1 : -1);
    if (authority == -1) return TEST_APP_INDEX;
    if (present[0] && present[1]) {
        if (entries[0].ota_seq == entries[1].ota_seq &&
            entries[0].ota_state != entries[1].ota_state) return TEST_APP_INDEX;
        if (entries[1].ota_seq > entries[0].ota_seq) authority = 1;
    }

    if (new_entry != -1) {
        const int peer = new_entry ^ 1;
        if (present[peer] && entries[peer].ota_seq > entries[new_entry].ota_seq &&
            entries[peer].ota_state != ESP_OTA_IMG_INVALID &&
            entries[peer].ota_state != ESP_OTA_IMG_ABORTED) return TEST_APP_INDEX;
        /* IDF188 can rewrite a lower-sequence active copy NEW in place when
         * the higher copy is INVALID/ABORTED. This exception relies on the
         * reviewed bootstrap + pinned update protocol, not imported metadata. */
        authority = new_entry;
    } else if (entries[authority].ota_state != ESP_OTA_IMG_VALID) {
        /* In particular keep PENDING durable: never let IDF turn it ABORTED
         * then try the same overwritten ota_0 through its no-factory fallback. */
        return TEST_APP_INDEX;
    }

    if (!mosaico_ota_keep_authority(bs, authority)) return TEST_APP_INDEX;
    /* Let the pinned SDK perform NEW -> PENDING, but do not trust its return
     * alone: its selector ignores an otadata erase/write failure. */
    if (new_entry != -1 && bootloader_utility_get_selected_boot_partition(bs) != 0)
        return TEST_APP_INDEX;
    esp_ota_select_entry_t after[2];
    if (bootloader_common_read_otadata(&bs->ota_info, after) != ESP_OK ||
        after[authority].ota_seq != entries[authority].ota_seq ||
        after[authority].ota_state != (new_entry != -1 ?
            ESP_OTA_IMG_PENDING_VERIFY : ESP_OTA_IMG_VALID) ||
        !mosaico_ota_record_crc_valid(&after[authority]) ||
        mosaico_ota_sector_erased(bs->ota_info.offset +
            (unsigned)(authority ^ 1) * MOSAICO_FLASH_SECTOR_BYTES) != 1)
        return TEST_APP_INDEX;
    return 0;
}
/* END MOSAICO_SINGLE_SLOT_POLICY */

static void stop_inherited_usb_dma(void)
{
    /* Panic/watchdog resets bypass application shutdown handlers. S31's SDK
     * leaves USB DMA running across CPU resets: stop it before loading any
     * application RAM segments that can overlap the previous USB buffers. */
    if (_usb_utmi_ll_bus_clock_is_enabled()) {
        usb_utmi_ll_reset_register();
        usb_utmi_ll_enable_bus_clock(false);
    }
}

static bool bootstrap_recovery_requested(const bootloader_state_t *bs)
{
    if (bs->ota_info.size != MOSAICO_OTADATA_BYTES) return false;
    char marker[MOSAICO_BOOTSTRAP_BYTES];
    return bootloader_flash_read(bs->ota_info.offset + MOSAICO_BOOTSTRAP_OFFSET,
        marker, sizeof(marker), true) == ESP_OK &&
        memcmp(marker, MOSAICO_BOOTSTRAP_MARKER, sizeof(marker)) == 0;
}

static bool software_recovery_requested(void)
{
    uint32_t intent = MOSAICO_BOOT_INTENT_NONE;
    esp_err_t err = mosaico_boot_read_intent(&intent);
    if (err == ESP_ERR_NVS_NOT_FOUND) return false;
    if (err != ESP_OK || (intent != MOSAICO_BOOT_INTENT_NONE &&
                          intent != MOSAICO_BOOT_INTENT_RECOVERY)) {
        ESP_LOGW(TAG, "Boot intent unavailable (%d); selecting Vibe Mode", err);
        return true;
    }
    return intent == MOSAICO_BOOT_INTENT_RECOVERY;
}

/* The AI button selects Vibe Mode after ROM boots this loader from Flash.
 * The separate Boot button selects ROM Download Mode before this code runs. */
static bool factory_recovery_requested(void)
{
    const uint32_t pin = CONFIG_FACTORY_RECOVERY_BOOT_GPIO;

    if (((1ULL << pin) & SOC_GPIO_VALID_GPIO_MASK) == 0) {
        ESP_LOGE(TAG, "Factory recovery GPIO %" PRIu32 " is not a valid input", pin);
        return false;
    }

    esp_rom_gpio_pad_select_gpio(pin);
    gpio_ll_input_enable(&GPIO, pin);
    esp_rom_gpio_pad_pullup_only(pin);

    if (gpio_ll_get_level(&GPIO, pin) != 0) {
        return false;
    }

    const uint32_t started_ms = esp_log_early_timestamp();
    while ((esp_log_early_timestamp() - started_ms) <
           CONFIG_FACTORY_RECOVERY_BOOT_DEBOUNCE_MS) {
        if (gpio_ll_get_level(&GPIO, pin) != 0) {
            ESP_LOGI(TAG, "Ignoring short low pulse on factory recovery GPIO %" PRIu32, pin);
            return false;
        }
    }

    return true;
}

/*
 * We arrive here after the ROM bootloader has loaded this second-stage
 * bootloader from flash. This remains aligned with ESP-IDF's default
 * bootloader entry flow; only partition selection is extended below.
 */
void __attribute__((noreturn)) call_start_cpu0(void)
{
    stop_inherited_usb_dma();
    if (bootloader_init() != ESP_OK) {
        bootloader_reset();
    }

    /* The retained Recovery bootloader owns the product's first visible
     * frame. Splash failures are deliberately non-fatal so display hardware
     * can never prevent Recovery or the normal application from booting. */
    (void)mosaico_boot_splash_show();

    /* Deep-sleep resumes must pass the same metadata guard as cold boots. */

    bootloader_state_t bs = {0};
    int boot_index = select_partition_number(&bs);
    if (boot_index == INVALID_INDEX) {
        bootloader_reset();
    }

#if CONFIG_SECURE_ENABLE_TEE
    bootloader_utility_load_tee_image(&bs);
#endif

    bootloader_utility_load_boot_image(&bs, boot_index);
}

static int select_partition_number(bootloader_state_t *bs)
{
    if (!bootloader_utility_load_partition_table(bs)) {
        ESP_LOGE(TAG, "load partition table error!");
        return INVALID_INDEX;
    }

    if (!mosaico_single_slot_layout(bs)) {
        ESP_LOGE(TAG, "Unsupported ABI 2 single-slot layout; refusing application scan");
        return INVALID_INDEX;
    }

    if (factory_recovery_requested() || bootstrap_recovery_requested(bs) ||
        software_recovery_requested()) {
        if (bs->test.offset == MOSAICO_RECOVERY_ADDRESS &&
            bs->test.size == MOSAICO_RECOVERY_BYTES) {
            ESP_LOGW(TAG,
                     "Maintenance requested; booting Vibe Mode (GPIO%d), preserving OTA data",
                     CONFIG_FACTORY_RECOVERY_BOOT_GPIO);
            return TEST_APP_INDEX;
        }
        ESP_LOGE(TAG, "Vibe Mode test partition is missing or has the wrong layout");
    }

    const int boot_index = selected_boot_partition(bs);
    if (boot_index == INVALID_INDEX && bs->test.offset == MOSAICO_RECOVERY_ADDRESS &&
        bs->test.size == MOSAICO_RECOVERY_BYTES) return TEST_APP_INDEX;
    ESP_LOGI(TAG, "Selected boot partition index=%d", boot_index);
    return boot_index;
}

/* The single-slot guard must precede IDF's multi-slot rollback fallback. */
static int selected_boot_partition(const bootloader_state_t *bs)
{
    return mosaico_single_slot_selected(bs);
}

#if CONFIG_LIBC_NEWLIB
struct _reent *__getreent(void)
{
    return _GLOBAL_REENT;
}
#endif
