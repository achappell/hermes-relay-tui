idf_component_register(SRCS "main.c" "../../../shared/touch_audio/capture_protocol.c" "../../../shared/touch_audio/capture_state.c"
    INCLUDE_DIRS "../../../shared/touch_audio" REQUIRES esp_driver_i2s esp_driver_uart esp_driver_gpio esp_timer)
