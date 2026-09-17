#pragma once

#include "esp_err.h"

/* Attach the Gateway's pointer RPC to the real LVGL display over USB. */
esp_err_t factory_ui_input_register(void);
