#include "sdkconfig.h"
#include "esp_attr.h"
#include "esp_cpu.h"
#include "esp_rom_sys.h"
#include <stdbool.h>

bool iris_services_restart_claimed(void);

/* Called only from the SDK's S31 restart translation unit. CPU-only warm
 * restarts after PSRAM-XIP updates have reached the final self-reset and then
 * fallen through to the RTC watchdog. Reset the digital domain at that point,
 * after the SDK has run shutdown handlers, written caches back and restored
 * clocks. Other-core resets and unclaimed SDK restarts keep SDK behavior. */
void IRAM_ATTR esp_iris_s31_restart_cpu_reset(int core_id)
{
    if (core_id != esp_cpu_get_core_id() || !iris_services_restart_claimed()) {
        esp_cpu_reset(core_id);
        return;
    }
#if !CONFIG_ESP_SYSTEM_SINGLE_CORE_MODE
    /* Digital reset preserves the LP-domain stall bits. Release the peer as
     * in the SDK's digital-reset path before asking ROM to reset the system. */
    esp_cpu_unstall(core_id ^ 1);
#endif
    esp_rom_software_reset_system();
    for (;;) { }
}
