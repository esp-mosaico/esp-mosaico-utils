"""Shared host-only CMake probes; never used by firmware configuration."""
import pytest


@pytest.fixture
def pinned_idf_probe(tmp_path):
    """Mock only the SDK identity boundary in component-discovery probes."""
    path = tmp_path / "pinned-idf-probe.cmake"
    path.write_text('''function(execute_process)
    if("${ARGV0}" STREQUAL "COMMAND" AND "${ARGV1}" STREQUAL "git" AND
       "${ARGV2}" STREQUAL "-C" AND "${ARGV3}" STREQUAL "$ENV{IDF_PATH}")
        cmake_parse_arguments(probe "" "RESULT_VARIABLE;OUTPUT_VARIABLE" "" ${ARGN})
        if("${ARGV4}" STREQUAL "rev-parse" AND "${ARGV5}" STREQUAL "HEAD")
            set(value "188e3e55bb20505b5fa9dc49ee390bf42c58b4ee")
        elseif("${ARGV4}" STREQUAL "diff" AND "${ARGV5}" STREQUAL "--name-only" AND
               "${ARGV6}" STREQUAL "HEAD" AND "${ARGV7}" STREQUAL "--")
            set(value "")
        else()
            message(FATAL_ERROR "Unexpected Git SDK identity query in test probe")
        endif()
        set(${probe_RESULT_VARIABLE} 0 PARENT_SCOPE)
        set(${probe_OUTPUT_VARIABLE} "${value}" PARENT_SCOPE)
        return()
    endif()
    _execute_process(${ARGV})
endfunction()
''')
    def project_probe(project):
        source = tmp_path / "cmake-project-probe"
        source.mkdir()
        (source / "CMakeLists.txt").write_text(
            'cmake_minimum_required(VERSION 3.16)\n'
            'include("' + path.as_posix() + '")\n'
            'include("' + (project / "CMakeLists.txt").as_posix() + '")\n'
        )
        return source
    return project_probe
