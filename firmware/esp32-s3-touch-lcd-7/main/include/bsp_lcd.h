#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_rgb.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef void (*bsp_lcd_vsync_cb_t)(void *user_data);

/**
 * @brief Initialize the 1024x600 (or 800x480) 16-bit RGB LCD peripheral.
 * @param on_vsync Optional VSYNC callback invoked at frame refresh (e.g. for LVGL).
 * @param user_data User pointer passed to the VSYNC callback.
 * @return ESP_OK on success.
 */
esp_err_t bsp_lcd_init(bsp_lcd_vsync_cb_t on_vsync, void *user_data);

/**
 * @brief Get the initialized LCD panel handle.
 */
esp_lcd_panel_handle_t bsp_lcd_get_panel_handle(void);

/**
 * @brief Get frame buffer pointers allocated in PSRAM.
 * @param fb0 Pointer to store first frame buffer.
 * @param fb1 Pointer to store second frame buffer (if double-buffered).
 */
esp_err_t bsp_lcd_get_frame_buffers(void **fb0, void **fb1);

/**
 * @brief Initialize CH422G-controlled backlight enable and PWM.
 */
esp_err_t bsp_lcd_backlight_init(void);

/**
 * @brief Set display backlight brightness.
 * @param percent Brightness level from 0 (off) to 100 (full).
 */
esp_err_t bsp_lcd_set_backlight(uint8_t percent);

#ifdef __cplusplus
}
#endif
