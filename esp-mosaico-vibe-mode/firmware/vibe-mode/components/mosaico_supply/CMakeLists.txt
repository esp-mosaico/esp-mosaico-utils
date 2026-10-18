idf_component_register(
    SRCS "mosaico_supply.c"
    PRIV_REQUIRES esp_system esp_hw_support esp_timer esp_rom riscv hal esp_hal_wdt soc
)
# The startup hook must be retained even when no application symbol references it.
target_link_options(${COMPONENT_LIB} INTERFACE
    "-Wl,--wrap=esp_restart_noos" "-Wl,-u,mosaico_supply_include")
