#include "bsp_touch.h"
#include "board_config.h"
#include "bsp_io_expander.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>

static const char *TAG = "bsp_touch";

#define GT911_REG_COMMAND       0x8040
#define GT911_REG_CONFIG_DATA   0x8047
#define GT911_REG_PID           0x8140
#define GT911_REG_STATUS        0x814E
#define GT911_REG_POINT1        0x814F

static uint8_t s_touch_i2c_addr = BOARD_TOUCH_GT911_ADDR_PRIMARY;
static bool s_touch_initialized = false;

static esp_err_t gt911_read_regs(uint16_t reg_addr, uint8_t *data, size_t len)
{
    uint8_t buffer[2] = { (uint8_t)(reg_addr >> 8), (uint8_t)(reg_addr & 0xFF) };
    return i2c_master_write_read_device(BOARD_I2C_PORT, s_touch_i2c_addr, buffer, 2, data, len, pdMS_TO_TICKS(50));
}

static esp_err_t gt911_write_regs(uint16_t reg_addr, const uint8_t *data, size_t len)
{
    uint8_t buffer[2 + len];
    buffer[0] = (uint8_t)(reg_addr >> 8);
    buffer[1] = (uint8_t)(reg_addr & 0xFF);
    if (len > 0 && data != NULL) {
        memcpy(&buffer[2], data, len);
    }
    return i2c_master_write_to_device(BOARD_I2C_PORT, s_touch_i2c_addr, buffer, 2 + len, pdMS_TO_TICKS(50));
}

esp_err_t bsp_touch_init(void)
{
    ESP_LOGI(TAG, "Initializing GT911 Capacitive Touch on I2C port %d (SDA: %d, SCL: %d)",
             BOARD_I2C_PORT, BOARD_I2C_PIN_SDA, BOARD_I2C_PIN_SCL);

    /* Initialize I2C driver if not already done */
    i2c_config_t conf = {
        .mode = I2C_MODE_MASTER,
        .sda_io_num = BOARD_I2C_PIN_SDA,
        .scl_io_num = BOARD_I2C_PIN_SCL,
        .sda_pullup_en = GPIO_PULLUP_ENABLE,
        .scl_pullup_en = GPIO_PULLUP_ENABLE,
        .master.clk_speed = BOARD_I2C_FREQ_HZ,
    };
    esp_err_t err = i2c_param_config(BOARD_I2C_PORT, &conf);
    if (err == ESP_OK) {
        i2c_driver_install(BOARD_I2C_PORT, conf.mode, 0, 0, 0);
    }

    /* Reset sequence to latch primary address 0x5D (INT pin held low during reset release) */
    gpio_config_t io_conf = {
        .pin_bit_mask = (1ULL << BOARD_TOUCH_PIN_INT),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_ENABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&io_conf);
    gpio_set_level(BOARD_TOUCH_PIN_INT, 0);

    bsp_io_expander_reset_touch();
    vTaskDelay(pdMS_TO_TICKS(50));

    /* Release INT pin to floating input */
    io_conf.mode = GPIO_MODE_INPUT;
    io_conf.pull_down_en = GPIO_PULLDOWN_DISABLE;
    gpio_config(&io_conf);
    vTaskDelay(pdMS_TO_TICKS(50));

    /* Probe GT911 address */
    uint8_t pid[4] = {0};
    s_touch_i2c_addr = BOARD_TOUCH_GT911_ADDR_PRIMARY;
    err = gt911_read_regs(GT911_REG_PID, pid, 4);
    if (err != ESP_OK) {
        s_touch_i2c_addr = BOARD_TOUCH_GT911_ADDR_SECONDARY;
        err = gt911_read_regs(GT911_REG_PID, pid, 4);
    }

    if (err == ESP_OK) {
        ESP_LOGI(TAG, "GT911 detected at address 0x%02X! Product ID: %c%c%c%c",
                 s_touch_i2c_addr, pid[0], pid[1], pid[2], pid[3]);
        s_touch_initialized = true;
        return ESP_OK;
    }

    ESP_LOGE(TAG, "GT911 touch controller probe failed on 0x5D and 0x14: %s", esp_err_to_name(err));
    return err;
}

esp_err_t bsp_touch_read(bsp_touch_data_t *touch_data)
{
    if (!s_touch_initialized || !touch_data) {
        return ESP_ERR_INVALID_STATE;
    }

    uint8_t status = 0;
    esp_err_t err = gt911_read_regs(GT911_REG_STATUS, &status, 1);
    if (err != ESP_OK) {
        return err;
    }

    /* Bit 7 = Buffer status ready, Bits 0..3 = Number of touch points */
    bool buffer_ready = (status & 0x80) != 0;
    uint8_t point_count = status & 0x0F;

    if (!buffer_ready || point_count == 0) {
        /* Clear status register */
        uint8_t zero = 0;
        gt911_write_regs(GT911_REG_STATUS, &zero, 1);
        touch_data->point_count = 0;
        return ESP_ERR_NOT_FOUND;
    }

    if (point_count > BOARD_TOUCH_MAX_POINTS) {
        point_count = BOARD_TOUCH_MAX_POINTS;
    }

    uint8_t raw_coords[point_count * 8];
    err = gt911_read_regs(GT911_REG_POINT1, raw_coords, point_count * 8);

    /* Clear status register immediately after reading */
    uint8_t zero = 0;
    gt911_write_regs(GT911_REG_STATUS, &zero, 1);

    if (err != ESP_OK) {
        return err;
    }

    touch_data->point_count = point_count;
    for (int i = 0; i < point_count; i++) {
        uint8_t *p = &raw_coords[i * 8];
        uint16_t x = p[1] | (p[2] << 8);
        uint16_t y = p[3] | (p[4] << 8);
        uint16_t size = p[5] | (p[6] << 8);

        /* Clamping to panel boundaries */
        if (x >= BOARD_LCD_H_RES) x = BOARD_LCD_H_RES - 1;
        if (y >= BOARD_LCD_V_RES) y = BOARD_LCD_V_RES - 1;

        touch_data->points[i].id = p[0];
        touch_data->points[i].x = x;
        touch_data->points[i].y = y;
        touch_data->points[i].size = size;
    }

    return ESP_OK;
}

uint8_t bsp_touch_get_i2c_addr(void)
{
    return s_touch_i2c_addr;
}
