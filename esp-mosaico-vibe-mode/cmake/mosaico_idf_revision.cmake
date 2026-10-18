# Recovery and its consumers must use the same reviewed S31 PMU/reset baseline.
include_guard(GLOBAL)
set(MOSAICO_REVIEWED_IDF_REVISION "188e3e55bb20505b5fa9dc49ee390bf42c58b4ee")
if(NOT DEFINED ENV{IDF_PATH} OR "$ENV{IDF_PATH}" STREQUAL "")
    message(FATAL_ERROR "Load the pinned ESP-IDF environment before configuring Mosaico")
endif()
execute_process(COMMAND git -C "$ENV{IDF_PATH}" rev-parse HEAD
    RESULT_VARIABLE mosaico_idf_result OUTPUT_VARIABLE mosaico_idf_revision
    OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
if(NOT mosaico_idf_result EQUAL 0 OR
   NOT mosaico_idf_revision STREQUAL MOSAICO_REVIEWED_IDF_REVISION)
    message(FATAL_ERROR "Mosaico requires ESP-IDF ${MOSAICO_REVIEWED_IDF_REVISION}; got ${mosaico_idf_revision}")
endif()
execute_process(COMMAND git -C "$ENV{IDF_PATH}" diff --name-only HEAD --
    RESULT_VARIABLE mosaico_idf_result OUTPUT_VARIABLE mosaico_idf_changes
    OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
if(NOT mosaico_idf_result EQUAL 0 OR NOT mosaico_idf_changes STREQUAL "")
    message(FATAL_ERROR "The reviewed Mosaico ESP-IDF checkout must not have tracked changes")
endif()
