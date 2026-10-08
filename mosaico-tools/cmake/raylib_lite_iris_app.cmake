# Build one Raylib Lite Engine native game as a managed ESP-Iris application.
# Include from a project CMakeLists.txt before project():
#
#   cmake_minimum_required(VERSION 3.16)
#   set(RAYLIB_LITE_GAME sky_hop)
#   include(/path/to/mosaico-tools/cmake/raylib_lite_iris_app.cmake)
#   project(${RAYLIB_LITE_GAME} VERSION 1.0.0)
#   raylib_lite_iris_link_game_board()
#   include("${MOSAICO_SYSTEM_UPDATE_CMAKE}")
#
# The project directory must contain templates/raylib_lite_iris/partitions.csv.
# `mosaico.py game build --target iris <game>` generates such a project.
# RAYLIB_LITE_ENGINE_ROOT and MOSAICO_BSP_ROOT are CMake or environment inputs.
include_guard(GLOBAL)

get_filename_component(_raylib_iris_tools "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)
get_filename_component(_raylib_iris_utils "${_raylib_iris_tools}/.." ABSOLUTE)
set(_raylib_iris_template "${_raylib_iris_tools}/templates/raylib_lite_iris")

if(NOT RAYLIB_LITE_ENGINE_ROOT AND DEFINED ENV{RAYLIB_LITE_ENGINE_ROOT})
    set(RAYLIB_LITE_ENGINE_ROOT "$ENV{RAYLIB_LITE_ENGINE_ROOT}")
endif()
if(NOT EXISTS "${RAYLIB_LITE_ENGINE_ROOT}/include/raylib_lite/raylib_lite_native_hooks.h")
    message(FATAL_ERROR
        "RAYLIB_LITE_ENGINE_ROOT must name a Raylib Lite Engine checkout with "
        "native lifecycle hooks: '${RAYLIB_LITE_ENGINE_ROOT}'")
endif()
get_filename_component(RAYLIB_LITE_ENGINE_ROOT "${RAYLIB_LITE_ENGINE_ROOT}" ABSOLUTE)

if(NOT RAYLIB_LITE_GAME)
    message(FATAL_ERROR "Set RAYLIB_LITE_GAME to an engine game; list them with "
        "'python3 ${RAYLIB_LITE_ENGINE_ROOT}/tools/game_cli.py list --json'")
endif()
set(_raylib_iris_game "${RAYLIB_LITE_ENGINE_ROOT}/examples/${RAYLIB_LITE_GAME}")
if(NOT EXISTS "${_raylib_iris_game}/main/CMakeLists.txt")
    message(FATAL_ERROR "${RAYLIB_LITE_GAME} is not a native engine game: ${_raylib_iris_game}")
endif()
if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/partitions.csv")
    message(FATAL_ERROR "Copy ${_raylib_iris_template}/partitions.csv into ${CMAKE_CURRENT_SOURCE_DIR}")
endif()

if(NOT SDKCONFIG)
    set(SDKCONFIG "${CMAKE_BINARY_DIR}/sdkconfig")
endif()
# Reuse the Engine's application-side Board and common native launcher.
# The Board owns Iris hooks already; do not link the legacy hook component.
set(SDKCONFIG_DEFAULTS "${_raylib_iris_template}/sdkconfig.defaults")
if(EXISTS "${_raylib_iris_game}/sdkconfig.defaults")
    list(APPEND SDKCONFIG_DEFAULTS "${_raylib_iris_game}/sdkconfig.defaults")
endif()
list(APPEND SDKCONFIG_DEFAULTS "${_raylib_iris_template}/sdkconfig.application.defaults")
# Keep Recovery and the product tools on the consuming workspace's revision.
set(FETCHCONTENT_SOURCE_DIR_RAYLIB_LITE_MOSAICO_UTILS "${_raylib_iris_utils}")
include("${RAYLIB_LITE_ENGINE_ROOT}/examples/common_components/examples_common/project.cmake")
list(APPEND EXTRA_COMPONENT_DIRS "${_raylib_iris_game}/main")
set(MOSAICO_ESP_IRIS_ROOT "${_raylib_iris_utils}/ESP-Iris")
set(MOSAICO_SYSTEM_UPDATE_CMAKE "${_raylib_iris_tools}/cmake/system_update.cmake")
include($ENV{IDF_PATH}/tools/cmake/project.cmake)

# An external Game main component does not receive IDF's local-main implicit
# dependencies. Preserve the explicit selected-Board link for its audio calls.
function(raylib_lite_iris_link_game_board)
    idf_component_get_property(_game_lib main COMPONENT_LIB)
    idf_component_get_property(_board_lib "${RAYLIB_LITE_BOARD}" COMPONENT_LIB)
    target_link_libraries(${_game_lib} PUBLIC ${_board_lib})
endfunction()
