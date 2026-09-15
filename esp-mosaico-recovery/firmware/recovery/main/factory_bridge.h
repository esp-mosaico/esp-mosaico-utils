#pragma once
#include "esp_err.h"

/* Explicit entry only; repeated entry while active is idempotent. */
esp_err_t factory_bridge_open(void);
