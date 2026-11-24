# For more information about build system see
# https://docs.espressif.com/projects/esp-idf/en/latest/api-guides/build-system.html
# The following five lines of boilerplate have to be in your project's
# CMakeLists in this exact order for cmake to work correctly
cmake_minimum_required(VERSION 3.16)

set(PROJECT_VER "2.0.1")

# Add this line to disable the specific warning
add_compile_options(-Wno-missing-field-initializers)
# The legacy image_player component uses %d for uint32_t logging fields.
# GCC 14 reports this as -Wformat; retain the warning but do not fail the build.
add_compile_options(-Wno-error=format)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(xiaozhi)

# This is appended after the managed component's own compile flags, so it
# overrides its legacy -Werror=format setting with GCC 14 / ESP-IDF 5.4.
if(TARGET __idf_espressif2022__image_player)
    target_compile_options(__idf_espressif2022__image_player PRIVATE -Wno-error=format)
endif()

