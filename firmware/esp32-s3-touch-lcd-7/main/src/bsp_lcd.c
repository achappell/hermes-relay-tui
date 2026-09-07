#include "bsp_lcd.h"
#include "board_config.h"
#include "bsp_io_expander.h"
#include "esp_log.h"
#include "driver/ledc.h"
#include "esp_heap_caps.h"

static const char *TAG = "bsp_lcd";

static esp_lcd_panel_handle_t s_panel_handle = NULL;
static bsp_lcd_vsync_cb_t s_vsync_cb = NULL;
static void *s_vsync_user_data = NULL;
static void *s_fb0 = NULL;
static void *s_fb1 = NULL;

static bool on_rgb_vsync_event(esp_lcd_panel_handle_t panel, const esp_lcd_rgb_panel_event_data_t *edata, void *user_ctx)
{
    if (s_vsync_cb) {
        s_vsync_cb(s_vsync_user_data);
    }
    return false;
}

esp_err_t bsp_lcd_init(bsp_lcd_vsync_cb_t on_vsync, void *user_data)
{
    s_vsync_cb = on_vsync;
    s_vsync_user_data = user_data;

    ESP_LOGI(TAG, "Initializing %s (%dx%d @ %d MHz)", 
             BOARD_NAME, BOARD_LCD_H_RES, BOARD_LCD_V_RES, BOARD_LCD_PIXEL_CLOCK_HZ / 1000000);

    /* Hardware reset via IO expander */
    bsp_io_expander_reset_lcd();

    esp_lcd_rgb_panel_config_t rgb_config = {
        .clk_src = LCD_CLK_SRC_DEFAULT,
        .timings = {
            .pclk_hz = BOARD_LCD_PIXEL_CLOCK_HZ,
            .h_res = BOARD_LCD_H_RES,
            .v_res = BOARD_LCD_V_RES,
            .hsync_pulse_width = BOARD_LCD_HSYNC_PULSE_WIDTH,
            .hsync_back_porch = BOARD_LCD_HSYNC_BACK_PORCH,
            .hsync_front_porch = BOARD_LCD_HSYNC_FRONT_PORCH,
            .vsync_pulse_width = BOARD_LCD_VSYNC_PULSE_WIDTH,
            .vsync_back_porch = BOARD_LCD_VSYNC_BACK_PORCH,
            .vsync_front_porch = BOARD_LCD_VSYNC_FRONT_PORCH,
            .flags = {
                .pclk_active_neg = BOARD_LCD_FLAGS_PCLK_ACTIVE_NEG,
                .de_idle_high = BOARD_LCD_FLAGS_DE_IDLE_HIGH,
                .pclk_idle_high = BOARD_LCD_FLAGS_PCLK_IDLE_HIGH,
            },
        },
        .data_width = 16,
        .bits_per_pixel = 16,
        .num_fbs = BOARD_LCD_NUM_FB,
        .bounce_buffer_size_px = BOARD_LCD_BOUNCE_BUFFER_PX,
        .sram_trans_align = 4,
        .psram_trans_align = 64,
        .hsync_gpio_num = BOARD_LCD_PIN_HSYNC,
        .vsync_gpio_num = BOARD_LCD_PIN_VSYNC,
        .de_gpio_num = BOARD_LCD_PIN_DE,
        .pclk_gpio_num = BOARD_LCD_PIN_PCLK,
        .disp_gpio_num = BOARD_LCD_PIN_DISP_EN,
        .data_gpio_nums = {
            BOARD_LCD_PIN_DATA0,
            BOARD_LCD_PIN_DATA1,
            BOARD_LCD_PIN_DATA2,
            BOARD_LCD_PIN_DATA3,
            BOARD_LCD_PIN_DATA4,
            BOARD_LCD_PIN_DATA5,
            BOARD_LCD_PIN_DATA6,
            BOARD_LCD_PIN_DATA7,
            BOARD_LCD_PIN_DATA8,
            BOARD_LCD_PIN_DATA9,
            BOARD_LCD_PIN_DATA10,
            BOARD_LCD_PIN_DATA11,
            BOARD_LCD_PIN_DATA12,
            BOARD_LCD_PIN_DATA13,
            BOARD_LCD_PIN_DATA14,
            BOARD_LCD_PIN_DATA15,
        },
        .flags = {
            .fb_in_psram = 1,
            .double_fb = (BOARD_LCD_NUM_FB > 1),
            .refresh_on_demand = 0,
        },
    };

    esp_err_t ret = esp_lcd_new_rgb_panel(&rgb_config, &s_panel_handle);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to create RGB LCD panel: %s", esp_err_to_name(ret));
        return ret;
    }

    /* Register VSYNC callback */
    esp_lcd_rgb_panel_event_callbacks_t cbs = {
        .on_vsync = on_rgb_vsync_event,
    };
    esp_lcd_rgb_panel_register_event_callbacks(s_panel_handle, &cbs, NULL);

    ret = esp_lcd_panel_reset(s_panel_handle);
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "esp_lcd_panel_reset returned %s", esp_err_to_name(ret));
    }

    ret = esp_lcd_panel_init(s_panel_handle);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to initialize RGB LCD panel: %s", esp_err_to_name(ret));
        return ret;
    }

    /* Fetch frame buffer pointers */
    esp_lcd_rgb_panel_get_frame_buffer(s_panel_handle, 2, &s_fb0, &s_fb1);
    ESP_LOGI(TAG, "RGB LCD frame buffers allocated in PSRAM: FB0=%p, FB1=%p (%u bytes each)",
             s_fb0, s_fb1, (unsigned int)(BOARD_LCD_H_RES * BOARD_LCD_V_RES * 2));

    return ESP_OK;
}

esp_lcd_panel_handle_t bsp_lcd_get_panel_handle(void)
{
    return s_panel_handle;
}

esp_err_t bsp_lcd_get_frame_buffers(void **fb0, void **fb1)
{
    if (!s_panel_handle) {
        return ESP_ERR_INVALID_STATE;
    }
    if (fb0) *fb0 = s_fb0;
    if (fb1) *fb1 = s_fb1;
    return ESP_OK;
}

esp_err_t bsp_lcd_backlight_init(void)
{
    /* Enable backlight power on IO expander */
    bsp_io_expander_set_backlight(true);

    /* Configure LEDC PWM for hardware brightness scaling on BOARD_BACKLIGHT_PIN */
    ledc_timer_config_t ledc_timer = {
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .duty_resolution = LEDC_TIMER_8_BIT,
        .timer_num = LEDC_TIMER_0,
        .freq_hz = BOARD_BACKLIGHT_PWM_FREQ_HZ,
        .clk_cfg = LEDC_AUTO_CLK
    };
    esp_err_t err = ledc_timer_config(&ledc_timer);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "LEDC timer config failed: %s", esp_err_to_name(err));
        return err;
    }

    ledc_channel_config_t ledc_channel = {
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel = LEDC_CHANNEL_0,
        .timer_sel = LEDC_TIMER_0,
        .intr_type = LEDC_INTR_DISABLE,
        .gpio_num = BOARD_BACKLIGHT_PIN,
        .duty = 0,
        .hpoint = 0
    };
    err = ledc_channel_config(&ledc_channel);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "LEDC channel config failed: %s", esp_err_to_name(err));
        return err;
    }

    return bsp_lcd_set_backlight(BOARD_BACKLIGHT_DEFAULT_PERCENT);
}

esp_err_t bsp_lcd_set_backlight(uint8_t percent)
{
    if (percent > 100) percent = 100;
    uint32_t duty = (percent * 255) / 100;
    ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, duty);
    return ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0);
}
