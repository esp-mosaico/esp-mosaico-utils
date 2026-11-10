cmake_minimum_required(VERSION 3.16)

# This project supplies IDF's native flasher and Iris's USB handoff. Its tiny
# application is only a configuration scaffold; only reviewed images are flashed.
set(MOSAICO_RECOVERY_SOURCE "reviewed" CACHE STRING "Reviewed bundle only")
if(NOT MOSAICO_RECOVERY_SOURCE STREQUAL "reviewed")
    message(FATAL_ERROR "Current source requires an explicit Vibe Mode project path")
endif()
set(RECOVERY_PREBUILT_DIR "${CMAKE_CURRENT_LIST_DIR}/../../firmware/recovery"
    CACHE PATH "Reviewed Recovery bundle")
if(NOT SDKCONFIG)
    set(SDKCONFIG "${CMAKE_BINARY_DIR}/sdkconfig")
endif()
set(COMPONENTS main)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(mosaico-recovery)

if(NOT CONFIG_IDF_TARGET_ESP32S31 OR NOT CONFIG_ESPTOOLPY_FLASHMODE_QIO
   OR CONFIG_SECURE_BOOT OR CONFIG_SECURE_FLASH_ENC_ENABLED)
    message(FATAL_ERROR "Reviewed Recovery requires ESP32-S31 QIO without secure boot or flash encryption")
endif()
idf_build_get_property(recovery_python PYTHON)
set(recovery_tool "${CMAKE_CURRENT_LIST_DIR}/../tools/prepare_recovery.py")
set(recovery_output_dir "${CMAKE_BINARY_DIR}/recovery")
if(NOT EXISTS "${RECOVERY_PREBUILT_DIR}/manifest.json")
    message(FATAL_ERROR
        "The reviewed Recovery bundle is not included in this checkout. "
        "Use the CI public snapshot or the published GitHub checkout.")
endif()
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
    "${RECOVERY_PREBUILT_DIR}/manifest.json")
file(READ "${RECOVERY_PREBUILT_DIR}/manifest.json" recovery_manifest)
string(JSON recovery_application GET "${recovery_manifest}" images recovery file)
partition_table_get_partition_info(recovery_offset "--partition-name vibe_mode" "offset")
partition_table_get_partition_info(recovery_size "--partition-name vibe_mode" "size")
partition_table_get_partition_info(normal_offset "--partition-name main_app" "offset")
partition_table_get_partition_info(ota_offset "--partition-name otadata" "offset")

# Always revalidate, including hashes and immutable partition layout, before a
# maintenance lease is acquired and again before the actual write target.
add_custom_target(recovery-image
    COMMAND "${recovery_python}" "${recovery_tool}"
        --bootloader "${RECOVERY_PREBUILT_DIR}/bootloader.bin"
        --partition-table "${RECOVERY_PREBUILT_DIR}/partition-table.bin"
        --ota-data "${RECOVERY_PREBUILT_DIR}/ota_data_initial.bin"
        --recovery "${RECOVERY_PREBUILT_DIR}/${recovery_application}"
        --manifest "${RECOVERY_PREBUILT_DIR}/manifest.json"
        --target "${IDF_TARGET}"
        --bootloader-offset "${CONFIG_BOOTLOADER_OFFSET_IN_FLASH}"
        --partition-table-offset "${CONFIG_PARTITION_TABLE_OFFSET}"
        --ota-data-offset "${ota_offset}"
        --recovery-offset "${recovery_offset}"
        --recovery-size "${recovery_size}"
        --normal-offset "${normal_offset}"
        --secure-boot 0 --flash-encryption 0
        --output-dir "${recovery_output_dir}"
    VERBATIM)
add_custom_target(mosaico-recover-prepare DEPENDS recovery-image)
# Iris's native callback runs 'all' before handing off USB. Finish these small
# public scaffold artifacts during preparation, before acquiring the device.
add_dependencies(mosaico-recover-prepare app bootloader partition_table_bin)
esptool_py_custom_target(mosaico-recover-flash mosaico_recover recovery-image)
esptool_py_flash_target_image(mosaico-recover-flash recovery_bootloader
    "${CONFIG_BOOTLOADER_OFFSET_IN_FLASH}" "${recovery_output_dir}/bootloader.bin")
esptool_py_flash_target_image(mosaico-recover-flash recovery_partition_table
    "${CONFIG_PARTITION_TABLE_OFFSET}" "${recovery_output_dir}/partition-table.bin")
esptool_py_flash_to_partition(mosaico-recover-flash otadata
    "${recovery_output_dir}/ota_data_initial.bin")
esptool_py_flash_to_partition(mosaico-recover-flash vibe_mode
    "${recovery_output_dir}/${recovery_application}")
