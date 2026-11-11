# Keep the SDK's shutdown/cache/clock sequence and adapt only its final S31
# CPU reset. Apply this after all component targets exist; never edit the SDK.
function(esp_iris_s31_restart_tail)
    idf_component_get_property(system_lib esp_system COMPONENT_LIB)
    get_target_property(sources ${system_lib} SOURCES)
    set(adapted 0)
    foreach(source IN LISTS sources)
        if(source MATCHES "(^|/)port/soc/esp32s31/system_internal\\.c$")
            set_property(SOURCE "${source}" TARGET_DIRECTORY ${system_lib}
                APPEND PROPERTY COMPILE_DEFINITIONS
                "esp_cpu_reset=esp_iris_s31_restart_cpu_reset")
            math(EXPR adapted "${adapted} + 1")
        endif()
    endforeach()
    if(NOT adapted EQUAL 1)
        message(FATAL_ERROR "Expected exactly one ESP32-S31 restart source, found ${adapted}")
    endif()
endfunction()
