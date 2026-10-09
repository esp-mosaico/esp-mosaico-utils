#include "esp_iris.h"

#include "sdkconfig.h"

#if CONFIG_ESP_IRIS_ENABLE
#include "esp_ota_ops.h"
#include "esp_partition.h"
#endif

esp_err_t __attribute__((weak)) esp_iris_platform_set_boot_target(uint32_t address)
{
#if CONFIG_ESP_IRIS_ENABLE
    esp_partition_iterator_t iterator = esp_partition_find(
        ESP_PARTITION_TYPE_APP, ESP_PARTITION_SUBTYPE_ANY, NULL);
    esp_err_t result = ESP_ERR_NOT_FOUND;
    while (iterator != NULL) {
        const esp_partition_t *partition = esp_partition_get(iterator);
        if (partition != NULL && partition->address == address) {
            result = esp_ota_set_boot_partition(partition);
            break;
        }
        iterator = esp_partition_next(iterator);
    }
    esp_partition_iterator_release(iterator);
    return result;
#else
    (void)address;
    return ESP_ERR_NOT_SUPPORTED;
#endif
}

esp_err_t __attribute__((weak)) esp_iris_platform_mark_healthy(void)
{
    return ESP_ERR_NOT_SUPPORTED;
}

esp_err_t __attribute__((weak)) esp_iris_platform_mark_planned_restart(void)
{
    return ESP_ERR_NOT_SUPPORTED;
}

void __attribute__((weak)) esp_iris_platform_ota_committed(void)
{
}

esp_err_t esp_iris_platform_select_recovery_target(uint32_t *target_address)
    __attribute__((weak));
esp_err_t esp_iris_platform_select_recovery_target(uint32_t *target_address)
{
    if (target_address == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
#if CONFIG_ESP_IRIS_ENABLE
    const esp_partition_t *factory = esp_partition_find_first(
        ESP_PARTITION_TYPE_APP, ESP_PARTITION_SUBTYPE_APP_FACTORY, NULL);
    if (factory == NULL) {
        return ESP_ERR_NOT_FOUND;
    }
    *target_address = factory->address;
    return ESP_OK;
#else
    *target_address = 0;
    return ESP_ERR_NOT_SUPPORTED;
#endif
}

esp_err_t esp_iris_platform_prepare_ota(uint32_t running_address,
                                        uint32_t target_address)
    __attribute__((weak));
esp_err_t esp_iris_platform_prepare_ota(uint32_t running_address,
                                        uint32_t target_address)
{
    (void)running_address;
    (void)target_address;
    /* Standard ESP-IDF OTA needs no product metadata. Retained-firmware
     * products override this hook before Iris commits the validated image. */
    return ESP_OK;
}

esp_err_t esp_iris_platform_select_ota_target(uint32_t default_address,
                                               uint32_t *target_address)
    __attribute__((weak));
esp_err_t esp_iris_platform_select_ota_target(uint32_t default_address,
                                               uint32_t *target_address)
{
    if (target_address == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    *target_address = default_address;
    return ESP_OK;
}
