# Normal applications consume the retained bootloader; never render its splash again.
# The caller supplies MOSAICO_BSP_ROOT before including this file and calling project().
include("${CMAKE_CURRENT_LIST_DIR}/mosaico_application.cmake")
set(MOSAICO_BOOT_SPLASH_IN_BOOTLOADER OFF)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
