#pragma once

#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Initialize the shared board I2C bus.
 *
 * The CH422G IO expander and GT911 touch controller share this bus. The
 * initialization is idempotent so either board service can safely request it.
 */
esp_err_t bsp_i2c_init(void);

#ifdef __cplusplus
}
#endif
