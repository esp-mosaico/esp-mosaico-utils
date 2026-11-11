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

static bool recovery_system_reset_required(uint32_t intent)
{
    return intent == MOSAICO_BOOT_INTENT_RECOVERY && esp_rom_get_reset_reason(0) == RESET_REASON_CPU_SW;
}

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
    if (recovery_system_reset_required(intent)) {
        /* A CPU-only restart preserves peripheral state. Re-enter through a
         * system reset before Vibe Mode consumes the retained intent. */
        ESP_LOGW(TAG, "Recovery intent after CPU reset; requesting system reset");
        bootloader_reset();
    }
    return intent == MOSAICO_BOOT_INTENT_RECOVERY;
}

_Static_assert(((1ULL << CONFIG_FACTORY_RECOVERY_BOOT_GPIO) & SOC_GPIO_VALID_GPIO_MASK) != 0,
               "Factory recovery GPIO is not a valid input");
_Static_assert(((1ULL << CONFIG_FACTORY_RECOVERY_LONG_PRESS_GPIO) & SOC_GPIO_VALID_GPIO_MASK) != 0,
               "Long-press recovery GPIO is not a valid input");

/* The AI button, or a long press on the power-switch net, selects Vibe Mode
 * after ROM boots this loader from Flash. Both pins are only read, never
 * driven. The separate Boot button selects ROM Download Mode before this
 * code runs. */
static bool factory_recovery_requested(void)
{
    const uint32_t ai_pin = CONFIG_FACTORY_RECOVERY_BOOT_GPIO;
    const uint32_t power_pin = CONFIG_FACTORY_RECOVERY_LONG_PRESS_GPIO;

    esp_rom_gpio_pad_select_gpio(ai_pin);
    gpio_ll_input_enable(&GPIO, ai_pin);
    esp_rom_gpio_pad_pullup_only(ai_pin);
    esp_rom_gpio_pad_select_gpio(power_pin);
    gpio_ll_input_enable(&GPIO, power_pin);
    esp_rom_gpio_pad_pullup_only(power_pin);

    bool ai_low = gpio_ll_get_level(&GPIO, ai_pin) == 0;
    bool power_low = gpio_ll_get_level(&GPIO, power_pin) == 0;
    if (!ai_low && !power_low) {
        return false;
    }

    /* Fixed 1 ms steps stay valid across 32-bit cycle-counter wraparound. */
    uint32_t elapsed_ms = 0;
    while (ai_low || power_low) {
        if ((ai_low && elapsed_ms >= CONFIG_FACTORY_RECOVERY_BOOT_DEBOUNCE_MS) ||
            (power_low && elapsed_ms >= CONFIG_FACTORY_RECOVERY_LONG_PRESS_MS)) {
            return true;
        }
        esp_rom_delay_us(1000);
        ++elapsed_ms;
        ai_low = ai_low && gpio_ll_get_level(&GPIO, ai_pin) == 0;
        power_low = power_low && gpio_ll_get_level(&GPIO, power_pin) == 0;
    }

    ESP_LOGI(TAG, "Ignoring %" PRIu32 " ms low pulse on factory recovery GPIO%" PRIu32 "/GPIO%" PRIu32,
             elapsed_ms, ai_pin, power_pin);
    return false;
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
    const bool splash_visible = mosaico_boot_splash_show();

    /* Every reset passes through the product's boot policy. */

    bootloader_state_t bs = {0};
    int boot_index = select_partition_number(&bs);
    if (boot_index == INVALID_INDEX) {
        bootloader_reset();
    }
    if (splash_visible) {
        (void)mosaico_boot_splash_draw(boot_index == TEST_APP_INDEX);
    }

#if CONFIG_SECURE_ENABLE_TEE
    bootloader_utility_load_tee_image(&bs);
#endif

    bootloader_utility_load_boot_image(&bs, boot_index);
}

/* Failed or unconfirmed OTA records return to Vibe Mode instead of retrying. */
static bool application_boot_allowed(const bootloader_state_t *bs)
{
    esp_ota_select_entry_t entries[2];
    if (bootloader_common_read_otadata(&bs->ota_info, entries) != ESP_OK) return false;
    int active = bootloader_common_get_active_otadata(entries);
    if (active < 0) {
        /* A native installation may have no OTA receipt yet. Failed records
         * must never be treated as a fresh installation. */
        return entries[0].ota_seq == UINT32_MAX && entries[1].ota_seq == UINT32_MAX;
    }
    if (entries[active].ota_state == ESP_OTA_IMG_PENDING_VERIFY) {
        /* Let IDF record the failed attempt before returning to Vibe Mode. */
        (void)bootloader_utility_get_selected_boot_partition(bs);
        ESP_LOGW(TAG, "Unconfirmed application; staying in Vibe Mode");
        return false;
    }
    return entries[active].ota_state == ESP_OTA_IMG_NEW || entries[active].ota_state == ESP_OTA_IMG_VALID ||
           entries[active].ota_state == ESP_OTA_IMG_UNDEFINED;
}

/* Deleting the installed IDEA erases its image header. Choosing Vibe Mode here
 * shows the Vibe Mode splash instead of relying on the loader's fallback. */
static bool application_image_present(const bootloader_state_t *bs, int index)
{
    if (index < FACTORY_INDEX) return true;
    const esp_partition_pos_t *part = index == FACTORY_INDEX ? &bs->factory : &bs->ota[index];
    uint32_t header = 0;
    return bootloader_flash_read(part->offset, &header, sizeof(header), true) == ESP_OK &&
           (header & 0xFF) == ESP_IMAGE_HEADER_MAGIC;
}

static int select_partition_number(bootloader_state_t *bs)
{
    if (!bootloader_utility_load_partition_table(bs)) {
        ESP_LOGE(TAG, "load partition table error!");
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

    if (!application_boot_allowed(bs) && bs->test.offset == MOSAICO_RECOVERY_ADDRESS &&
        bs->test.size == MOSAICO_RECOVERY_BYTES) {
        ESP_LOGI(TAG, "Boot policy selected Vibe Mode");
        return TEST_APP_INDEX;
    }
    const int boot_index = selected_boot_partition(bs);
    if ((boot_index == INVALID_INDEX || !application_image_present(bs, boot_index)) &&
        bs->test.offset == MOSAICO_RECOVERY_ADDRESS && bs->test.size == MOSAICO_RECOVERY_BYTES) {
        ESP_LOGI(TAG, "No application image; booting Vibe Mode");
        return TEST_APP_INDEX;
    }
    ESP_LOGI(TAG, "Selected boot partition index=%d", boot_index);
    return boot_index;
}

/* Keep ESP-IDF's standard OTA, rollback, factory-reset, and test-app rules. */
static int selected_boot_partition(const bootloader_state_t *bs)
{
    int boot_index = bootloader_utility_get_selected_boot_partition(bs);
    if (boot_index == INVALID_INDEX) {
        return boot_index;
    }

    if (esp_rom_get_reset_reason(0) != RESET_REASON_CORE_DEEP_SLEEP) {
#ifdef CONFIG_BOOTLOADER_FACTORY_RESET
        bool reset_level = false;
#if CONFIG_BOOTLOADER_FACTORY_RESET_PIN_HIGH
        reset_level = true;
#endif
        if (bootloader_common_check_long_hold_gpio_level(
                CONFIG_BOOTLOADER_NUM_PIN_FACTORY_RESET,
                CONFIG_BOOTLOADER_HOLD_TIME_GPIO,
                reset_level) == GPIO_LONG_HOLD) {
            ESP_LOGI(TAG, "Detect a condition of the factory reset");
            bool ota_data_erase = false;
#ifdef CONFIG_BOOTLOADER_OTA_DATA_ERASE
            ota_data_erase = true;
#endif
            const char *list_erase = CONFIG_BOOTLOADER_DATA_FACTORY_RESET;
            ESP_LOGI(TAG, "Data partitions to erase: %s", list_erase);
            if (!bootloader_common_erase_part_type_data(list_erase, ota_data_erase)) {
                ESP_LOGE(TAG, "Not all partitions were erased");
            }
#ifdef CONFIG_BOOTLOADER_RESERVE_RTC_MEM
            bootloader_common_set_rtc_retain_mem_factory_reset_state();
#endif
            return bootloader_utility_get_selected_boot_partition(bs);
        }
#endif

#ifdef CONFIG_BOOTLOADER_APP_TEST
        bool app_test_level = false;
#if CONFIG_BOOTLOADER_APP_TEST_PIN_HIGH
        app_test_level = true;
#endif
        if (bootloader_common_check_long_hold_gpio_level(
                CONFIG_BOOTLOADER_NUM_PIN_APP_TEST,
                CONFIG_BOOTLOADER_HOLD_TIME_GPIO,
                app_test_level) == GPIO_LONG_HOLD) {
            ESP_LOGI(TAG, "Detect a boot condition of the test firmware");
            if (bs->test.offset != 0) {
                return TEST_APP_INDEX;
            }
            ESP_LOGE(TAG, "Test firmware is not found in partition table");
            return INVALID_INDEX;
        }
#endif
    }

    return boot_index;
}

#if CONFIG_LIBC_NEWLIB
struct _reent *__getreent(void)
{
    return _GLOBAL_REENT;
}
#endif
