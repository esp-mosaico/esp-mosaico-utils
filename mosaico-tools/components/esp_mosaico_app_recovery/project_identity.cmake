# A caller may pin a project identity across moves/clones. Otherwise the
# canonical project directory provides a stable local identity across builds,
# while unrelated projects with the same CMake name remain distinct.
function(mosaico_resolve_project_identity project_dir out_var)
    if(DEFINED MOSAICO_APP_PROJECT_ID AND NOT MOSAICO_APP_PROJECT_ID STREQUAL "")
        string(LENGTH "${MOSAICO_APP_PROJECT_ID}" id_length)
        if(NOT id_length EQUAL 32 OR MOSAICO_APP_PROJECT_ID MATCHES "[^0-9a-f]")
            message(FATAL_ERROR "MOSAICO_APP_PROJECT_ID must be 32 lowercase hexadecimal characters")
        endif()
        set(identity "${MOSAICO_APP_PROJECT_ID}")
    else()
        get_filename_component(canonical_dir "${project_dir}" REALPATH)
        string(SHA256 identity "mosaico-project-v1:${canonical_dir}")
        string(SUBSTRING "${identity}" 0 32 identity)
    endif()
    set(${out_var} "${identity}" PARENT_SCOPE)
endfunction()
