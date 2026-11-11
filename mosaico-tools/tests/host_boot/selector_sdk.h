#pragma once
#include "sdk.h"
#include <stdlib.h>
#include <string.h>
#define CONFIG_FACTORY_RECOVERY_BOOT_GPIO 7
#define CONFIG_FACTORY_RECOVERY_BOOT_DEBOUNCE_MS 50
#define CONFIG_FACTORY_RECOVERY_LONG_PRESS_GPIO 57
#define CONFIG_FACTORY_RECOVERY_LONG_PRESS_MS 300
#define SOC_GPIO_VALID_GPIO_MASK ((1ULL << 7) | (1ULL << 57))
#define RESET_REASON_CORE_DEEP_SLEEP 5
#define RESET_REASON_CPU_SW 12
#define INVALID_INDEX (-99)
#define TEST_APP_INDEX (-2)
#define FACTORY_INDEX (-1)
#define ESP_IMAGE_HEADER_MAGIC 0xE9
#define NVS_TYPE_U32 4
#define ESP_LOG_ATTR_TAG(name, text) static const char *name __attribute__((unused)) = text
#define ESP_LOGE(...) ((void)0)
#define ESP_LOGW(...) ((void)0)
#define ESP_LOGI(...) ((void)0)
typedef struct { esp_partition_pos_t test, ota_info, factory, ota[2]; } bootloader_state_t;
typedef struct {
    const char *namespace_name, *key_name;
    int value_type;
    esp_err_t result_code;
    union { uint32_t u32_val; } value;
} nvs_bootloader_read_list_t;
static int GPIO;
static int gpio_level = 1, selected, table_ok = 1;
static esp_err_t nvs_error, key_error = ESP_ERR_NVS_NOT_FOUND;
static uint32_t intent;
static uint8_t bootstrap[16], app_header[16] = {ESP_IMAGE_HEADER_MAGIC};
static unsigned writes;
static int reset_reason;
static esp_err_t ota_error;
enum { ESP_OTA_IMG_NEW, ESP_OTA_IMG_PENDING_VERIFY, ESP_OTA_IMG_VALID,
       ESP_OTA_IMG_INVALID, ESP_OTA_IMG_ABORTED, ESP_OTA_IMG_UNDEFINED = UINT32_MAX };
typedef struct { uint32_t ota_seq, ota_state; bool crc_valid; } esp_ota_select_entry_t;
static esp_ota_select_entry_t ota_entries[2];
static inline esp_err_t bootloader_common_read_otadata(const esp_partition_pos_t *p, esp_ota_select_entry_t *out)
{ memcpy(out, ota_entries, sizeof(ota_entries)); return ota_error; }
static inline int bootloader_common_get_active_otadata(const esp_ota_select_entry_t *entries)
{
    int active = -1;
    for (int i = 0; i < 2; ++i) {
        if (entries[i].ota_seq == UINT32_MAX || !entries[i].crc_valid ||
            entries[i].ota_state == ESP_OTA_IMG_ABORTED || entries[i].ota_state == ESP_OTA_IMG_INVALID) continue;
        if (active < 0 || entries[i].ota_seq > entries[active].ota_seq) active = i;
    }
    return active;
}
static bool usb_clock;
static unsigned usb_resets;
static inline bool _usb_utmi_ll_bus_clock_is_enabled(void) { return usb_clock; }
static inline void usb_utmi_ll_reset_register(void) { ++usb_resets; }
static inline void usb_utmi_ll_enable_bus_clock(bool enabled) { usb_clock = enabled; }
static inline esp_err_t bootloader_init(void) { return ESP_OK; }
static inline __attribute__((noreturn)) void bootloader_reset(void) { abort(); }
static inline bool mosaico_boot_splash_show(void) { return true; }
static inline bool mosaico_boot_splash_draw(bool vibe_mode) { (void)vibe_mode; return true; }
static inline bool bootloader_utility_load_partition_table(bootloader_state_t *bs) { return table_ok; }
static inline __attribute__((noreturn)) void bootloader_utility_load_boot_image(bootloader_state_t *bs, int i) { abort(); }
static inline int bootloader_utility_get_selected_boot_partition(const bootloader_state_t *bs) {
    for (int i = 0; i < 2; ++i) {
        if (ota_entries[i].ota_state == ESP_OTA_IMG_PENDING_VERIFY) ota_entries[i].ota_state = ESP_OTA_IMG_ABORTED;
    }
    int active = bootloader_common_get_active_otadata(ota_entries);
    if (active >= 0 && ota_entries[active].ota_state == ESP_OTA_IMG_NEW)
        ota_entries[active].ota_state = ESP_OTA_IMG_PENDING_VERIFY;
    return selected;
}
static inline esp_err_t bootloader_flash_read(size_t off, void *data, size_t size, bool decrypt)
{ memcpy(data, off == 0x210000 ? app_header : bootstrap, size); return ESP_OK; }
static inline esp_err_t nvs_bootloader_read(const char *p, size_t n, nvs_bootloader_read_list_t *e)
{ e->result_code = key_error; e->value.u32_val = intent; return nvs_error; }
static inline esp_err_t mosaico_boot_read_intent(uint32_t *value)
{ *value = intent; return nvs_error == ESP_OK ? key_error : nvs_error; }
static inline void esp_rom_gpio_pad_select_gpio(unsigned pin) { }
static inline void gpio_ll_input_enable(int *gpio, unsigned pin) { }
static inline void esp_rom_gpio_pad_pullup_only(unsigned pin) { }
static int long_press_level = 1;
static uint32_t held_us, long_press_release_us;
static inline void esp_rom_delay_us(uint32_t us) { held_us += us; }
static inline int gpio_ll_get_level(int *gpio, unsigned pin)
{
    if (pin != CONFIG_FACTORY_RECOVERY_LONG_PRESS_GPIO) return gpio_level;
    return long_press_release_us != 0 && held_us >= long_press_release_us ? 1 : long_press_level;
}
static inline int esp_rom_get_reset_reason(int cpu) { return reset_reason; }
