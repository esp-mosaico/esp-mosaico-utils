#pragma once
#include "esp_err.h"

/* Explicit entry promotes an existing prefetched session without registering. */
esp_err_t factory_bridge_open(void);
esp_err_t factory_bridge_prefetch(void);
