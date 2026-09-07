#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "esp_system.h"
#include "esp_log.h"
#include "esp_chip_info.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"

#include "board_config.h"
#include "bsp_io_expander.h"
#include "bsp_lcd.h"
#include "bsp_touch.h"
#include "ui_test.h"

#if __has_include("lvgl.h")
    #include "lvgl.h"
    #define HAVE_LVGL 1
#elif __has_include("lvgl/lvgl.h")
    #include "lvgl/lvgl.h"
    #define HAVE_LVGL 1
#else
    #define HAVE_LVGL 0
#endif

static const char *TAG = "main";
static SemaphoreHandle_t s_lvgl_mutex = NULL;

#if HAVE_LVGL
static void lvgl_flush_cb(lv_disp_drv_t *drv, const lv_area_t *area, lv_color_t *color_map)
{
    esp_lcd_panel_handle_t panel_handle = (esp_lcd_panel_handle_t)drv->user_data;
    int offsetx1 = area->x1;
    int offsetx2 = area->x2;
    int offsety1 = area->y1;
    int offsety2 = area->y2;

    /* Flush frame to RGB LCD panel */
    esp_lcd_panel_draw_bitmap(panel_handle, offsetx1, offsety1, offsetx2 + 1, offsety2 + 1, color_map);
    lv_disp_flush_ready(drv);
}

static void lvgl_touch_read_cb(lv_indev_drv_t *drv, lv_indev_data_t *data)
{
    bsp_touch_data_t touch_data;
    esp_err_t err = bsp_touch_read(&touch_data);

    if (err == ESP_OK && touch_data.point_count > 0) {
        data->state = LV_INDEV_STATE_PRESSED;
        data->point.x = touch_data.points[0].x;
        data->point.y = touch_data.points[0].y;
    } else {
        data->state = LV_INDEV_STATE_RELEASED;
    }
}

static void lvgl_ui_task(void *pvParameters)
{
    ESP_LOGI(TAG, "LVGL UI Task started on Core %d", xPortGetCoreID());

    uint32_t frame_count = 0;
    int64_t last_fps_time = esp_timer_get_time();
    uint32_t current_fps = 0;

    while (1) {
        if (pdTRUE == xSemaphoreTake(s_lvgl_mutex, portMAX_DELAY)) {
            uint32_t task_delay_ms = lv_timer_handler();
            
            /* Read touch state for UI updates */
            bsp_touch_data_t touch_data;
            esp_err_t err = bsp_touch_read(&touch_data);
            bool touch_active = (err == ESP_OK && touch_data.point_count > 0);
            uint16_t tx = touch_active ? touch_data.points[0].x : 0;
            uint16_t ty = touch_active ? touch_data.points[0].y : 0;
            uint8_t count = touch_active ? touch_data.point_count : 0;

            frame_count++;
            int64_t now = esp_timer_get_time();
            if (now - last_fps_time >= 1000000) {
                current_fps = (frame_count * 1000000) / (now - last_fps_time);
                frame_count = 0;
                last_fps_time = now;
            }

            ui_test_update_touch(touch_active, tx, ty, count, current_fps);
            xSemaphoreGive(s_lvgl_mutex);

            if (task_delay_ms < 1) task_delay_ms = 1;
            if (task_delay_ms > 16) task_delay_ms = 16;
            vTaskDelay(pdMS_TO_TICKS(task_delay_ms));
        }
    }
}
#endif

void app_main(void)
{
    ESP_LOGI(TAG, "=================================================");
    ESP_LOGI(TAG, " Hermes Smart Display — ESP-01 Hardware Bring-Up");
    ESP_LOGI(TAG, " Target: %s", BOARD_NAME);
    ESP_LOGI(TAG, "=================================================");

    /* 1. Log Chip Information */
    esp_chip_info_t chip_info;
    esp_chip_info(&chip_info);
    ESP_LOGI(TAG, "ESP32-S3 Cores: %d, Silicon Revision: %d", chip_info.cores, chip_info.revision);

    /* 2. Verify Octal PSRAM */
    size_t psram_size = heap_caps_get_total_size(MALLOC_CAP_SPIRAM);
    size_t psram_free = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
    size_t sram_free = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);

    ESP_LOGI(TAG, "PSRAM Total: %u KB, Free: %u KB", (unsigned int)(psram_size / 1024), (unsigned int)(psram_free / 1024));
    ESP_LOGI(TAG, "Internal SRAM Free: %u KB", (unsigned int)(sram_free / 1024));

    if (psram_size < 4 * 1024 * 1024) {
        ESP_LOGE(TAG, "CRITICAL: Expected >= 8MB Octal PSRAM, detected %u KB! Check sdkconfig / board definition.",
                 (unsigned int)(psram_size / 1024));
    }

    /* 3. Initialize I2C and IO Expander */
    bsp_io_expander_init();

    /* 4. Initialize Backlight */
    bsp_lcd_backlight_init();

    /* 5. Initialize 1024x600 RGB LCD */
    esp_err_t err = bsp_lcd_init(NULL, NULL);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "LCD Initialization failed: %s", esp_err_to_name(err));
        return;
    }

    /* 6. Initialize GT911 Capacitive Touch */
    err = bsp_touch_init();
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "Touch initialization returned: %s", esp_err_to_name(err));
    }

    /* 7. Initialize LVGL & UI Task */
#if HAVE_LVGL
    s_lvgl_mutex = xSemaphoreCreateMutex();
    lv_init();

    /* Setup LVGL display buffer using PSRAM double buffers */
    void *fb0 = NULL, *fb1 = NULL;
    bsp_lcd_get_frame_buffers(&fb0, &fb1);

    static lv_disp_draw_buf_t disp_buf;
    lv_disp_draw_buf_init(&disp_buf, fb0, fb1, BOARD_LCD_H_RES * BOARD_LCD_V_RES);

    static lv_disp_drv_t disp_drv;
    lv_disp_drv_init(&disp_drv);
    disp_drv.hor_res = BOARD_LCD_H_RES;
    disp_drv.ver_res = BOARD_LCD_V_RES;
    disp_drv.flush_cb = lvgl_flush_cb;
    disp_drv.draw_buf = &disp_buf;
    disp_drv.user_data = bsp_lcd_get_panel_handle();
    disp_drv.direct_mode = 1;
    lv_disp_drv_register(&disp_drv);

    /* Register Touch Input Device */
    static lv_indev_drv_t indev_drv;
    lv_indev_drv_init(&indev_drv);
    indev_drv.type = LV_INDEV_TYPE_POINTER;
    indev_drv.read_cb = lvgl_touch_read_cb;
    lv_indev_drv_register(&indev_drv);

    /* Initialize Bring-up Test Scene */
    ui_test_init();

    /* Launch UI Task pinned to Core 1 */
    xTaskCreatePinnedToCore(lvgl_ui_task, "lvgl_ui", 8192, NULL, 5, NULL, 1);
#else
    ESP_LOGI(TAG, "Direct mode test complete. Framebuffers active.");
#endif

    ESP_LOGI(TAG, "Firmware initialization complete. Hardware ready.");
}
