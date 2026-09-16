idf_component_register(
    SRCS
        "bootloader_start.c"
        "mosaico_boot_splash.c"
    REQUIRES
        bootloader
        bootloader_support
        efuse
        esp_hal_gpio
        esp_hal_gpspi
        esp_rom
        hal
        soc
)

# Keep the default ESP-IDF bootloader linker layout.
idf_build_get_property(scripts BOOTLOADER_LINKER_SCRIPT)
target_linker_script(${COMPONENT_LIB} INTERFACE "${scripts}")
