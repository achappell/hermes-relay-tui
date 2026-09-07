cmake_minimum_required(VERSION 3.16)
project(esp32_s3_touch_lcd_7_simulator C)

set(CMAKE_C_STANDARD 11)

# Find SDL2
find_package(SDL2 REQUIRED)

# Fetch or include LVGL 8.3.11
include(FetchContent)
FetchContent_Declare(
    lvgl
    GIT_REPOSITORY https://github.com/lvgl/lvgl.git
    GIT_TAG v8.3.11
)
FetchContent_MakeAvailable(lvgl)

# Include directories
include_directories(
    ${CMAKE_CURRENT_SOURCE_DIR}/../main/include
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../shared/display
    ${SDL2_INCLUDE_DIRS}
    ${lvgl_SOURCE_DIR}
)

# Simulator executable
add_executable(esp32_display_sim
    sdl_main.c
    ../main/src/ui_snapshot.c
    ../main/src/ui_display.c
    ../main/src/ui_test.c
    ../../../shared/display/display_rules.c
)

target_compile_definitions(esp32_display_sim PRIVATE
    LV_CONF_INCLUDE_SIMPLE
    SIMULATOR_BUILD=1
)

target_link_libraries(esp32_display_sim PRIVATE
    lvgl
    lvgl::lvgl
    ${SDL2_LIBRARIES}
)
