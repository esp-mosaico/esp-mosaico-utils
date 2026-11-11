// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Shared ABI 2 boot policy. These functions never restart the processor.
 * NVS commits are atomic. The caller must serialize transitions across tasks
 * and owns restart order; these are not ISR or panic-handler entry points. */
esp_err_t mosaico_boot_request_recovery(void);
esp_err_t mosaico_boot_select(uint32_t address);
/* Explicit retry from Vibe Mode only. Validate/select the OTA image, clear its
 * crash-loop quarantine and mark a planned restart. The caller holds the NOR
 * lease and must not restart on failure. Preserves Core Dump and preferences. */
esp_err_t mosaico_boot_retry_application(uint32_t address);
/* Consume maintenance intent from Vibe Mode, normally early at startup.
 * Boot selection may also clear it while owning the NOR transition. */
esp_err_t mosaico_boot_consume_request(void);
esp_err_t mosaico_boot_recovery_requested(bool *requested);

#ifdef __cplusplus
}
#endif
