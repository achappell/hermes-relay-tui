#include "bsp_i2c.h"
#include "board_config.h"
#include "driver/i2c.h"
#include "esp_log.h"

static const char *TAG = "bsp_i2c";
static bool s_i2c_initialized = false;

esp_err_t bsp_i2c_init(void)
{
    if (s_i2c_initialized) {
        return ESP_OK;
    }

    const i2c_config_t config = {
        .mode = I2C_MODE_MASTER,
        .sda_io_num = BOARD_I2C_PIN_SDA,
        .scl_io_num = BOARD_I2C_PIN_SCL,
        .sda_pullup_en = GPIO_PULLUP_ENABLE,
        .scl_pullup_en = GPIO_PULLUP_ENABLE,
        .master.clk_speed = BOARD_I2C_FREQ_HZ,
    };

    esp_err_t err = i2c_param_config(BOARD_I2C_PORT, &config);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "I2C parameter configuration failed: %s", esp_err_to_name(err));
        return err;
    }

    err = i2c_driver_install(BOARD_I2C_PORT, config.mode, 0, 0, 0);
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        ESP_LOGE(TAG, "I2C driver installation failed: %s", esp_err_to_name(err));
        return err;
    }

    s_i2c_initialized = true;
    ESP_LOGI(TAG, "I2C%d ready on SDA=%d, SCL=%d at %d Hz",
             BOARD_I2C_PORT, BOARD_I2C_PIN_SDA, BOARD_I2C_PIN_SCL, BOARD_I2C_FREQ_HZ);
    return ESP_OK;
}
