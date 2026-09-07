#include "bsp_io_expander.h"
#include "board_config.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "bsp_io_expander";
static bsp_expander_type_t s_expander_type = EXPANDER_TYPE_NONE;
static uint8_t s_output_state = 0xFF;

esp_err_t bsp_io_expander_init(void)
{
    /* Probe CH422G first */
    uint8_t dummy = 0x01;
    esp_err_t err = i2c_master_write_to_device(BOARD_I2C_PORT, BOARD_EXPANDER_CH422G_ADDR, &dummy, 1, pdMS_TO_TICKS(50));
    if (err == ESP_OK) {
        s_expander_type = EXPANDER_TYPE_CH422G;
        ESP_LOGI(TAG, "Detected CH422G IO Expander at 0x%02X", BOARD_EXPANDER_CH422G_ADDR);
        /* Set initial output state: all high */
        s_output_state = 0xFF;
        uint8_t cmd[2] = {0x00, s_output_state};
        i2c_master_write_to_device(BOARD_I2C_PORT, BOARD_EXPANDER_CH422G_ADDR, cmd, 2, pdMS_TO_TICKS(50));
        return ESP_OK;
    }

    /* Probe PCA9554 */
    uint8_t reg_cfg = 0x03; /* Configuration register */
    uint8_t cfg_val = 0x00; /* All outputs */
    uint8_t data[2] = {reg_cfg, cfg_val};
    err = i2c_master_write_to_device(BOARD_I2C_PORT, BOARD_EXPANDER_PCA9554_ADDR, data, 2, pdMS_TO_TICKS(50));
    if (err == ESP_OK) {
        s_expander_type = EXPANDER_TYPE_PCA9554;
        ESP_LOGI(TAG, "Detected PCA9554 IO Expander at 0x%02X", BOARD_EXPANDER_PCA9554_ADDR);
        s_output_state = 0xFF;
        uint8_t out_cmd[2] = {0x01, s_output_state}; /* Output port register */
        i2c_master_write_to_device(BOARD_I2C_PORT, BOARD_EXPANDER_PCA9554_ADDR, out_cmd, 2, pdMS_TO_TICKS(50));
        return ESP_OK;
    }

    ESP_LOGW(TAG, "No dedicated IO expander detected; using direct GPIO / defaults");
    s_expander_type = EXPANDER_TYPE_NONE;
    return ESP_ERR_NOT_FOUND;
}

bsp_expander_type_t bsp_io_expander_get_type(void)
{
    return s_expander_type;
}

esp_err_t bsp_io_expander_set_level(uint8_t pin_num, uint8_t level)
{
    if (s_expander_type == EXPANDER_TYPE_NONE) {
        return ESP_ERR_INVALID_STATE;
    }

    if (level) {
        s_output_state |= (1 << pin_num);
    } else {
        s_output_state &= ~(1 << pin_num);
    }

    if (s_expander_type == EXPANDER_TYPE_CH422G) {
        uint8_t cmd[2] = {0x00, s_output_state};
        return i2c_master_write_to_device(BOARD_I2C_PORT, BOARD_EXPANDER_CH422G_ADDR, cmd, 2, pdMS_TO_TICKS(50));
    } else if (s_expander_type == EXPANDER_TYPE_PCA9554) {
        uint8_t cmd[2] = {0x01, s_output_state};
        return i2c_master_write_to_device(BOARD_I2C_PORT, BOARD_EXPANDER_PCA9554_ADDR, cmd, 2, pdMS_TO_TICKS(50));
    }

    return ESP_FAIL;
}

void bsp_io_expander_reset_lcd(void)
{
    if (s_expander_type != EXPANDER_TYPE_NONE) {
        bsp_io_expander_set_level(BOARD_EXP_PIN_LCD_RST, 0);
        vTaskDelay(pdMS_TO_TICKS(20));
        bsp_io_expander_set_level(BOARD_EXP_PIN_LCD_RST, 1);
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

void bsp_io_expander_reset_touch(void)
{
    if (s_expander_type != EXPANDER_TYPE_NONE) {
        bsp_io_expander_set_level(BOARD_EXP_PIN_TP_RST, 0);
        vTaskDelay(pdMS_TO_TICKS(20));
        bsp_io_expander_set_level(BOARD_EXP_PIN_TP_RST, 1);
        vTaskDelay(pdMS_TO_TICKS(50));
    } else {
        /* Direct GPIO reset */
        gpio_set_direction(BOARD_TOUCH_PIN_RST, GPIO_MODE_OUTPUT);
        gpio_set_level(BOARD_TOUCH_PIN_RST, 0);
        vTaskDelay(pdMS_TO_TICKS(20));
        gpio_set_level(BOARD_TOUCH_PIN_RST, 1);
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

void bsp_io_expander_set_backlight(bool enable)
{
    if (s_expander_type != EXPANDER_TYPE_NONE) {
        bsp_io_expander_set_level(BOARD_EXP_PIN_LCD_BL, enable ? 1 : 0);
    }
}
