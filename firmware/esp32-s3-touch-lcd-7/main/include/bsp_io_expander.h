#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    EXPANDER_TYPE_NONE = 0,
    EXPANDER_TYPE_CH422G
} bsp_expander_type_t;

/**
 * @brief Initialize the onboard CH422G IO expander at 0x24.
 * @return ESP_OK on success, or the I2C error from the probe.
 */
esp_err_t bsp_io_expander_init(void);

/**
 * @brief Get the detected expander type.
 */
bsp_expander_type_t bsp_io_expander_get_type(void);

/**
 * @brief Set the output level of a pin on the IO expander.
 * @param pin_num Pin number on expander (0..7)
 * @param level 0 for LOW, 1 for HIGH
 */
esp_err_t bsp_io_expander_set_level(uint8_t pin_num, uint8_t level);

/**
 * @brief Reset LCD panel via the CH422G IO expander.
 */
esp_err_t bsp_io_expander_reset_lcd(void);

/**
 * @brief Reset Touch controller via the CH422G IO expander.
 */
esp_err_t bsp_io_expander_reset_touch(void);

/**
 * @brief Enable/disable the LCD display output via CH422G EXIO2.
 */
esp_err_t bsp_io_expander_set_backlight(bool enable);

/**
 * @brief Set CH422G-controlled backlight brightness.
 * @param percent Brightness level from 0 to 100 (capped at 97 by the board).
 */
esp_err_t bsp_io_expander_set_brightness(uint8_t percent);

#ifdef __cplusplus
}
#endif
