#pragma once
#include "esp_iris.h"

esp_err_t iris_test_network_start(void);
esp_err_t iris_test_network_rpc(const esp_iris_rpc_request_t *request,
                               uint8_t *response, size_t capacity,
                               size_t *size, void *user_ctx);
