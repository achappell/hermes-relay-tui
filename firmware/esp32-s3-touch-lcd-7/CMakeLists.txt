cmake_minimum_required(VERSION 3.16)

# Installation values are deliberately absent from version control.
if(EXISTS "${CMAKE_CURRENT_LIST_DIR}/sdkconfig.installation")
    set(SDKCONFIG_DEFAULTS "sdkconfig.defaults;sdkconfig.installation")
endif()
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(hermes_esp32_s3_touch_lcd_7)

# Compile LVGL and the application against the same hardware configuration.
idf_component_get_property(lvgl_lib lvgl__lvgl COMPONENT_LIB)
target_include_directories(${lvgl_lib} PUBLIC "${CMAKE_CURRENT_LIST_DIR}/main/include")
if(CONFIG_LV_CONF_SKIP)
    message(FATAL_ERROR "Disable CONFIG_LV_CONF_SKIP: this target requires main/include/lv_conf.h")
endif()
