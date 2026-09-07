#include "bsp_io_expander.h"
#include "board_config.h"
#include "bsp_i2c.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "bsp_io_expander";
static bsp_expander_type_t s_expander_type = EXPANDER_TYPE_NONE;
static uint8_t s_output_state = 0xFF;

esp_err_t bsp_io_expander_init(void)
{
    esp_err_t err = bsp_i2c_init();
    if (err != ESP_OK) {
        return err;
    }

    /* The Waveshare board uses a CH422G at 0x24. Configure all EXIO pins as
     * outputs; this write also acts as the presence probe. */
    uint8_t mode_cmd[2] = {0x02, 0xFF};
    err = i2c_master_write_to_device(BOARD_I2C_PORT, BOARD_EXPANDER_CH422G_ADDR,
                                     mode_cmd, sizeof(mode_cmd), pdMS_TO_TICKS(50));
    if (err == ESP_OK) {
        s_expander_type = EXPANDER_TYPE_CH422G;
        ESP_LOGI(TAG, "Detected CH422G IO Expander at 0x%02X", BOARD_EXPANDER_CH422G_ADDR);
        /* Set initial output state: all high */
        s_output_state = 0xFF;
        uint8_t cmd[2] = {0x03, s_output_state};
        err = i2c_master_write_to_device(BOARD_I2C_PORT, BOARD_EXPANDER_CH422G_ADDR,
                                         cmd, sizeof(cmd), pdMS_TO_TICKS(50));
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "CH422G output initialization failed: %s", esp_err_to_name(err));
            s_expander_type = EXPANDER_TYPE_NONE;
            return err;
        }
        return ESP_OK;
    }

    ESP_LOGE(TAG, "CH422G probe failed at 0x%02X: %s", BOARD_EXPANDER_CH422G_ADDR,
             esp_err_to_name(err));
    s_expander_type = EXPANDER_TYPE_NONE;
    return err;
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
    if (pin_num > 7) {
        return ESP_ERR_INVALID_ARG;
    }

    uint8_t next_output_state = s_output_state;
    if (level) {
        next_output_state |= (uint8_t)(1U << pin_num);
    } else {
        next_output_state &= (uint8_t)~(1U << pin_num);
    }

    if (s_expander_type == EXPANDER_TYPE_CH422G) {
        uint8_t cmd[2] = {0x03, next_output_state};
        esp_err_t err = i2c_master_write_to_device(BOARD_I2C_PORT, BOARD_EXPANDER_CH422G_ADDR,
                                                   cmd, sizeof(cmd), pdMS_TO_TICKS(50));
        if (err == ESP_OK) {
            s_output_state = next_output_state;
        }
        return err;
    }

    return ESP_FAIL;
}

esp_err_t bsp_io_expander_reset_lcd(void)
{
    if (s_expander_type == EXPANDER_TYPE_NONE) {
        return ESP_ERR_INVALID_STATE;
    }

    esp_err_t err = bsp_io_expander_set_level(BOARD_EXP_PIN_LCD_RST, 0);
    if (err != ESP_OK) return err;
    vTaskDelay(pdMS_TO_TICKS(20));
    err = bsp_io_expander_set_level(BOARD_EXP_PIN_LCD_RST, 1);
    if (err != ESP_OK) return err;
    vTaskDelay(pdMS_TO_TICKS(50));
    return ESP_OK;
}

esp_err_t bsp_io_expander_reset_touch(void)
{
    if (s_expander_type == EXPANDER_TYPE_NONE) {
        return ESP_ERR_INVALID_STATE;
    }

    esp_err_t err = bsp_io_expander_set_level(BOARD_EXP_PIN_TP_RST, 0);
    if (err != ESP_OK) return err;
    vTaskDelay(pdMS_TO_TICKS(20));
    err = bsp_io_expander_set_level(BOARD_EXP_PIN_TP_RST, 1);
    if (err != ESP_OK) return err;
    vTaskDelay(pdMS_TO_TICKS(100));
    return ESP_OK;
}

esp_err_t bsp_io_expander_set_backlight(bool enable)
{
    if (s_expander_type == EXPANDER_TYPE_CH422G) {
        return bsp_io_expander_set_level(BOARD_EXP_PIN_DISP, enable ? 1 : 0);
    }
    return ESP_ERR_INVALID_STATE;
}

esp_err_t bsp_io_expander_set_brightness(uint8_t percent)
{
    if (s_expander_type != EXPANDER_TYPE_CH422G) {
        return ESP_ERR_INVALID_STATE;
    }

    /* The CH422G PWM register is 8-bit and the board example caps brightness
     * at 97% so the boost converter is never driven fully on. */
    if (percent >= 97) {
        percent = 97;
    }
    uint8_t cmd[2] = {0x05, (uint8_t)((percent * 255) / 100)};
    return i2c_master_write_to_device(BOARD_I2C_PORT, BOARD_EXPANDER_CH422G_ADDR,
                                      cmd, sizeof(cmd), pdMS_TO_TICKS(50));
}
