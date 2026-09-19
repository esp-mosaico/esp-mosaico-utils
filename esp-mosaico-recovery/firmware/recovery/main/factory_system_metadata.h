#pragma once

#include <stdint.h>

#include "esp_err.h"
#include "esp_iris_system_inventory.h"
#include "mosaico_recovery_contract.h"

#define FACTORY_SYSTEM_METADATA_PARTITION MOSAICO_SYSMETA_PARTITION
#define FACTORY_SYSTEM_METADATA_OTA_NAMESPACE MOSAICO_OTA_NAMESPACE

#define FACTORY_SYSTEM_METADATA_MAGIC MOSAICO_SYSMETA_MAGIC
#define FACTORY_SYSTEM_METADATA_VERSION MOSAICO_SYSMETA_VERSION

typedef mosaico_sysmeta_record_t factory_sysmeta_record_t;
_Static_assert(ESP_IRIS_SYSTEM_OPERATION_ID_BYTES == MOSAICO_OPERATION_ID_BYTES,
               "Iris operation ID must fit the Mosaico product ABI");

esp_err_t factory_system_metadata_init(void);
esp_err_t factory_system_metadata_load_last_result(
    factory_sysmeta_record_t *record);
esp_err_t factory_system_metadata_store_last_result(
    const uint8_t operation_id[ESP_IRIS_SYSTEM_OPERATION_ID_BYTES],
    esp_err_t result);
