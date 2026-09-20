#pragma once

#include "esp_err.h"
#include "esp_gsp.h"

/* Attach the Gateway's pointer RPC to the GSP display over USB. */
esp_err_t factory_ui_input_register(void);

/* Internal display handle shared by the GSP input adapter. */
esp_gsp_handle_t factory_ui_handle(void);
