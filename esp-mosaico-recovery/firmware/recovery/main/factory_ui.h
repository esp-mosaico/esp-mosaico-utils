#pragma once

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t factory_ui_start(void);

/* Explicitly enter Bridge download mode through the same page as touch UI.
 * An active session is left intact; a completed one may be opened again. */
esp_err_t factory_ui_open_bridge(void);

#ifdef __cplusplus
}
#endif
