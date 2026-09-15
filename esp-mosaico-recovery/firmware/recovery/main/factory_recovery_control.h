#pragma once

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Register USB-only Recovery control methods used to configure Wi-Fi and to
 * open and query the Bridge download session. */
esp_err_t factory_recovery_control_register(void);

#ifdef __cplusplus
}
#endif
