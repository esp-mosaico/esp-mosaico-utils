idf_component_register(
    SRCS "iris_ota_support.c" "mosaico_shared.c"
    INCLUDE_DIRS "include"
    PRIV_INCLUDE_DIRS "../../include"
    REQUIRES
        app_update
        esp_app_format
        esp_iris
        esp_mosaico_boot
        esp_partition
        freertos
        mbedtls
        nvs_flash
        spi_flash
)

if(DEFINED COMPONENT_LIB AND TARGET "${COMPONENT_LIB}" AND CONFIG_ESP_IRIS_FIRMWARE_ROLE EQUAL 1)
    include("${CMAKE_CURRENT_LIST_DIR}/project_identity.cmake")
    idf_build_get_property(mosaico_project_dir PROJECT_DIR)
    mosaico_resolve_project_identity("${mosaico_project_dir}" mosaico_project_id)
    configure_file("${CMAKE_CURRENT_LIST_DIR}/project_identity.c.in"
        "${CMAKE_CURRENT_BINARY_DIR}/mosaico_project_identity.c" @ONLY)
    target_sources(${COMPONENT_LIB} PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/mosaico_project_identity.c")
    target_link_libraries(${COMPONENT_LIB} INTERFACE "-u mosaico_app_identity")
endif()

# Defaults do not override a previously generated sdkconfig. Fail here rather
# than producing firmware that can install once but cannot return to Recovery.
file(STRINGS "${CMAKE_CURRENT_LIST_DIR}/sdkconfig.defaults" mosaico_contract
    REGEX "^CONFIG_.*=")
foreach(entry IN LISTS mosaico_contract)
    string(REGEX MATCH "^([^=]+)=(.*)$" unused "${entry}")
    set(key "${CMAKE_MATCH_1}")
    string(REPLACE "\"" "" expected "${CMAKE_MATCH_2}")
    if(NOT key MATCHES "^CONFIG_ESP_IRIS_" AND
       NOT key STREQUAL "CONFIG_ESPTOOLPY_FLASHMODE_QIO")
        continue()
    endif()
    if(expected STREQUAL "y")
        if(NOT ${key})
            message(FATAL_ERROR "Mosaico application requires ${key}=y; update sdkconfig and rebuild")
        endif()
    elseif(NOT "${${key}}" STREQUAL "${expected}")
        message(FATAL_ERROR "Mosaico application requires ${key}=${expected}; update sdkconfig and rebuild")
    endif()
endforeach()
if(CONFIG_ESP_IRIS_OTA)
    message(FATAL_ERROR "Mosaico application must disable CONFIG_ESP_IRIS_OTA; Recovery owns the writer")
endif()
