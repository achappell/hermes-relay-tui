#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    EXPANDER_TYPE_NONE = 0,
    EXPANDER_TYPE_CH422G,
    EXPANDER_TYPE_PCA9554
} bsp_expander_type_t;

/**
 * @brief Initialize the onboard IO expander (auto-detects CH422G / PCA9554).
 * @return ESP_OK on success, or ESP_ERR_NOT_FOUND if neither expander responds.
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
 * @brief Reset LCD panel via IO expander or GPIO.
 */
void bsp_io_expander_reset_lcd(void);

/**
 * @brief Reset Touch controller via IO expander or GPIO.
 */
void bsp_io_expander_reset_touch(void);

/**
 * @brief Enable/disable LCD backlight via IO expander.
 */
void bsp_io_expander_set_backlight(bool enable);

#ifdef __cplusplus
}
#endif
