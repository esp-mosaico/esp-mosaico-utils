idf_component_register(SRCS "native_services.c" "iris_display_input.c"
    PRIV_INCLUDE_DIRS "."
    REQUIRES raylib-lite-engine esp_iris esp_mosaico_app_recovery
    PRIV_REQUIRES esp_timer freertos heap
    WHOLE_ARCHIVE)
if(NOT CONFIG_ESP_IRIS_ENABLE OR NOT CONFIG_ESP_IRIS_TRANSPORT_USB OR
        NOT CONFIG_ESP_IRIS_OTA_DEFAULT_VIA_RECOVERY OR
        CONFIG_ESP_MOSAICO_APP_AUTO_ACCEPT)
    message(FATAL_ERROR "Raylib Iris games require USB Iris, Recovery-first updates and explicit first-frame health confirmation")
endif()
