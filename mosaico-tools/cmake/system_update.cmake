# Build the local, unsigned ESP-Iris System Update bundle used by
# `python mosaico.py iris system-update --project projects/<application>`.
# The application supplies its partition layout and binary; the retained
# Recovery bootloader is intentionally not part of normal application updates.
# It is installed and repaired only by `mosaico.py recover`.

# The product's test partition is excluded from IDF's normal application
# selection. Its matching bootloader is built by esp_mosaico_app_recovery.
# Verify both labels and subtypes before enabling native flash/app-flash.
idf_build_get_property(mosaico_native_python PYTHON)
execute_process(COMMAND "${mosaico_native_python}"
    "${CMAKE_CURRENT_LIST_DIR}/../tools/validate_native_layout.py"
    "${PROJECT_SOURCE_DIR}/partitions.csv"
    RESULT_VARIABLE mosaico_native_layout_result
    ERROR_VARIABLE mosaico_native_layout_error)
if(NOT mosaico_native_layout_result EQUAL 0)
    message(FATAL_ERROR "${mosaico_native_layout_error}")
endif()
partition_table_get_partition_info(mosaico_native_application
    "--partition-type app --partition-subtype ota_0" "name")
partition_table_get_partition_info(mosaico_native_recovery
    "--partition-type app --partition-subtype test" "name")
partition_table_get_partition_info(mosaico_native_factory
    "--partition-type app --partition-subtype factory" "offset")
if(NOT mosaico_native_application STREQUAL "main_app" OR
   NOT mosaico_native_recovery STREQUAL "vibe_mode" OR mosaico_native_factory)
    message(FATAL_ERROR "Native Mosaico flashing requires the 0.2 test/main_app layout")
endif()

set(system_update_preparer
    "${CMAKE_CURRENT_LIST_DIR}/../tools/prepare_system_update.py")
set(system_update_partition_csv "${PROJECT_SOURCE_DIR}/partitions.csv")
if(MOSAICO_ESP_IRIS_ROOT)
    set(system_update_iris_root "${MOSAICO_ESP_IRIS_ROOT}")
else()
    set(system_update_iris_root
        "${CMAKE_CURRENT_LIST_DIR}/../../ESP-Iris")
endif()
set(system_update_iris_tool
    "${system_update_iris_root}/components/esp_iris/tools/esp_iris.py")
set(system_update_stage_dir "${CMAKE_BINARY_DIR}/system-update")
set(system_update_bundle
    "${CMAKE_BINARY_DIR}/${PROJECT_NAME}-system-update.irisfw")
get_property(system_update_ui_apps GLOBAL PROPERTY
    MOSAICO_SYSTEM_UPDATE_UI_APPS_IMAGE)
get_property(system_update_ui_apps_target GLOBAL PROPERTY
    MOSAICO_SYSTEM_UPDATE_UI_APPS_TARGET)
set(system_update_preparer_args "")
set(system_update_dependencies "")
if(system_update_ui_apps)
    list(APPEND system_update_preparer_args
        --ui-apps "${system_update_ui_apps}")
    list(APPEND system_update_dependencies
        "${system_update_ui_apps}" ${system_update_ui_apps_target})
endif()

# Each resource producer declares its label, generated image, and build target.
get_property(system_update_data_labels GLOBAL PROPERTY MOSAICO_SYSTEM_UPDATE_DATA_LABELS)
foreach(label IN LISTS system_update_data_labels)
    get_property(data_image GLOBAL PROPERTY "MOSAICO_SYSTEM_UPDATE_DATA_${label}_IMAGE")
    get_property(data_target GLOBAL PROPERTY "MOSAICO_SYSTEM_UPDATE_DATA_${label}_TARGET")
    if(NOT data_image OR NOT data_target)
        message(FATAL_ERROR "System Update resource ${label} requires IMAGE and TARGET properties")
    endif()
    list(APPEND system_update_preparer_args --data "${label}=${data_image}")
    list(APPEND system_update_dependencies "${data_image}" "${data_target}")
endforeach()

# The ESP-Iris bundle builder imports Gateway runtime dependencies (for
# example zeroconf), so mosaico.py passes its prepared host Python explicitly.
if(DEFINED ESP_IRIS_PYTHON AND EXISTS "${ESP_IRIS_PYTHON}")
    set(system_update_python "${ESP_IRIS_PYTHON}")
elseif(DEFINED ENV{ESP_IRIS_PYTHON} AND EXISTS "$ENV{ESP_IRIS_PYTHON}")
    set(system_update_python "$ENV{ESP_IRIS_PYTHON}")
else()
    set(system_update_python "")
endif()

if(system_update_python)
    add_custom_target(system-update-bundle
        COMMAND "${CMAKE_COMMAND}" -E rm -rf "${system_update_stage_dir}"
        COMMAND "${system_update_python}" "${system_update_preparer}"
            --partition-csv "${system_update_partition_csv}"
            --partition-table
                "${CMAKE_BINARY_DIR}/partition_table/partition-table.bin"
            --application "${CMAKE_BINARY_DIR}/${PROJECT_NAME}.bin"
            ${system_update_preparer_args}
            --stage-dir "${system_update_stage_dir}"
            --release "${PROJECT_VERSION}"
        COMMAND "${system_update_python}" "${system_update_iris_tool}"
            bundle build "${system_update_stage_dir}/manifest.json"
            --component-root "${system_update_stage_dir}"
            --output "${system_update_bundle}"
        DEPENDS "${system_update_preparer}"
                "${system_update_partition_csv}"
                "${system_update_iris_tool}" app
                partition_table_bin ${system_update_dependencies}
        BYPRODUCTS "${system_update_bundle}"
        COMMENT "Building application + data + system update bundle"
        VERBATIM)
else()
    add_custom_target(system-update-bundle
        COMMAND "${CMAKE_COMMAND}" -E echo
            "ESP-Iris host environment unavailable; use mosaico.py iris system-update"
        COMMAND "${CMAKE_COMMAND}" -E false
        VERBATIM)
endif()

message(STATUS "ESP-Iris System Update bundle: ${system_update_bundle}")
