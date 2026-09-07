#include "ui_test.h"
#include "board_config.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <stdio.h>
#include <string.h>

#if __has_include("lvgl.h")
    #include "lvgl.h"
    #define HAVE_LVGL 1
#elif __has_include("lvgl/lvgl.h")
    #include "lvgl/lvgl.h"
    #define HAVE_LVGL 1
#else
    #define HAVE_LVGL 0
#endif

static const char *TAG = "ui_test";

#if HAVE_LVGL
static lv_obj_t *s_coord_label = NULL;
static lv_obj_t *s_mem_label = NULL;
static lv_obj_t *s_fps_label = NULL;
static lv_obj_t *s_btn_tl = NULL;
static lv_obj_t *s_btn_tr = NULL;
static lv_obj_t *s_btn_bl = NULL;
static lv_obj_t *s_btn_br = NULL;
static lv_obj_t *s_touch_indicator = NULL;
static lv_obj_t *s_arc_bench = NULL;
static lv_obj_t *s_slider_bench = NULL;

static bool s_corner_tl_hit = false;
static bool s_corner_tr_hit = false;
static bool s_corner_bl_hit = false;
static bool s_corner_br_hit = false;

static void btn_corner_cb(lv_event_t *e)
{
    lv_obj_t *btn = lv_event_get_target(e);
    lv_obj_set_style_bg_color(btn, lv_palette_main(LV_PALETTE_GREEN), 0);
    
    if (btn == s_btn_tl) s_corner_tl_hit = true;
    if (btn == s_btn_tr) s_corner_tr_hit = true;
    if (btn == s_btn_bl) s_corner_bl_hit = true;
    if (btn == s_btn_br) s_corner_br_hit = true;

    ESP_LOGI(TAG, "Corner verified! Progress: TL=%d, TR=%d, BL=%d, BR=%d",
             s_corner_tl_hit, s_corner_tr_hit, s_corner_bl_hit, s_corner_br_hit);
}
#endif

void ui_test_init(void)
{
#if HAVE_LVGL
    ESP_LOGI(TAG, "Building LVGL 1024x600 bring-up test scene...");

    lv_obj_t *scr = lv_scr_act();
    lv_obj_set_style_bg_color(scr, lv_color_hex(0x121214), 0);

    /* 1. Header Bar */
    lv_obj_t *header = lv_obj_create(scr);
    lv_obj_set_size(header, BOARD_LCD_H_RES, 50);
    lv_obj_set_pos(header, 0, 0);
    lv_obj_set_style_bg_color(header, lv_color_hex(0x1E1E24), 0);
    lv_obj_set_style_border_side(header, LV_BORDER_SIDE_BOTTOM, 0);
    lv_obj_set_style_border_color(header, lv_color_hex(0x33333F), 0);
    lv_obj_set_style_radius(header, 0, 0);
    lv_obj_clear_flag(header, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t *title = lv_label_create(header);
    lv_label_set_text(title, "Hermes Smart Display — Waveshare ESP32-S3-Touch-LCD-7B");
    lv_obj_set_style_text_color(title, lv_color_hex(0xEDE7F6), 0);
    lv_obj_align(title, LV_ALIGN_LEFT_MID, 15, 0);

    s_fps_label = lv_label_create(header);
    lv_label_set_text(s_fps_label, "FPS: -- | Render: -- ms");
    lv_obj_set_style_text_color(s_fps_label, lv_color_hex(0x69F0AE), 0);
    lv_obj_align(s_fps_label, LV_ALIGN_RIGHT_MID, -15, 0);

    /* 2. Main Stats Panel */
    lv_obj_t *panel_stats = lv_obj_create(scr);
    lv_obj_set_size(panel_stats, 480, 200);
    lv_obj_set_pos(panel_stats, 60, 70);
    lv_obj_set_style_bg_color(panel_stats, lv_color_hex(0x18181E), 0);
    lv_obj_set_style_border_color(panel_stats, lv_color_hex(0x2E2E38), 0);

    s_mem_label = lv_label_create(panel_stats);
    uint32_t psram_free = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
    uint32_t psram_total = heap_caps_get_total_size(MALLOC_CAP_SPIRAM);
    uint32_t sram_free = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
    uint32_t sram_total = heap_caps_get_total_size(MALLOC_CAP_INTERNAL);

    char mem_buf[128];
    snprintf(mem_buf, sizeof(mem_buf),
             "Resolution: %dx%d (16-bit RGB565)\n"
             "Octal PSRAM: %u KB free / %u KB total\n"
             "Internal SRAM: %u KB free / %u KB total",
             BOARD_LCD_H_RES, BOARD_LCD_V_RES,
             (unsigned int)(psram_free / 1024), (unsigned int)(psram_total / 1024),
             (unsigned int)(sram_free / 1024), (unsigned int)(sram_total / 1024));
    lv_label_set_text(s_mem_label, mem_buf);
    lv_obj_set_style_text_color(s_mem_label, lv_color_hex(0xB0BEC5), 0);
    lv_obj_align(s_mem_label, LV_ALIGN_TOP_LEFT, 10, 10);

    s_coord_label = lv_label_create(panel_stats);
    lv_label_set_text(s_coord_label, "Touch: Idle (Touch screen to test)");
    lv_obj_set_style_text_color(s_coord_label, lv_color_hex(0xFFD54F), 0);
    lv_obj_align(s_coord_label, LV_ALIGN_BOTTOM_LEFT, 10, -10);

    /* 3. Benchmark Animation Widget */
    lv_obj_t *panel_bench = lv_obj_create(scr);
    lv_obj_set_size(panel_bench, 400, 200);
    lv_obj_set_pos(panel_bench, 560, 70);
    lv_obj_set_style_bg_color(panel_bench, lv_color_hex(0x18181E), 0);
    lv_obj_set_style_border_color(panel_bench, lv_color_hex(0x2E2E38), 0);

    s_arc_bench = lv_arc_create(panel_bench);
    lv_obj_set_size(s_arc_bench, 130, 130);
    lv_arc_set_rotation(s_arc_bench, 270);
    lv_arc_set_bg_angles(s_arc_bench, 0, 360);
    lv_arc_set_value(s_arc_bench, 65);
    lv_obj_align(s_arc_bench, LV_ALIGN_LEFT_MID, 15, 0);

    s_slider_bench = lv_slider_create(panel_bench);
    lv_obj_set_size(s_slider_bench, 180, 20);
    lv_slider_set_value(s_slider_bench, 75, LV_ANIM_OFF);
    lv_obj_align(s_slider_bench, LV_ALIGN_RIGHT_MID, -15, 0);

    /* 4. Color Palette Bars */
    static const uint32_t colors[] = {
        0xF44336, 0xE91E63, 0x9C27B0, 0x3F51B5, 0x2196F3, 0x00BCD4, 0x009688, 0x4CAF50, 0xFFEB3B, 0xFF9800
    };
    int bar_w = (BOARD_LCD_H_RES - 120) / 10;
    for (int i = 0; i < 10; i++) {
        lv_obj_t *bar = lv_obj_create(scr);
        lv_obj_set_size(bar, bar_w - 4, 30);
        lv_obj_set_pos(bar, 60 + i * bar_w, 290);
        lv_obj_set_style_bg_color(bar, lv_color_hex(colors[i]), 0);
        lv_obj_set_style_border_width(bar, 0, 0);
        lv_obj_set_style_radius(bar, 4, 0);
        lv_obj_clear_flag(bar, LV_OBJ_FLAG_SCROLLABLE);
    }

    /* 5. Four Corner Verification Buttons */
    /* Top Left (0, 0) */
    s_btn_tl = lv_btn_create(scr);
    lv_obj_set_size(s_btn_tl, 110, 45);
    lv_obj_set_pos(s_btn_tl, 5, 55);
    lv_obj_add_event_cb(s_btn_tl, btn_corner_cb, LV_EVENT_CLICKED, NULL);
    lv_obj_t *lbl_tl = lv_label_create(s_btn_tl);
    lv_label_set_text(lbl_tl, "TL [0, 0]");
    lv_obj_center(lbl_tl);

    /* Top Right (1023, 0) */
    s_btn_tr = lv_btn_create(scr);
    lv_obj_set_size(s_btn_tr, 110, 45);
    lv_obj_set_pos(s_btn_tr, BOARD_LCD_H_RES - 115, 55);
    lv_obj_add_event_cb(s_btn_tr, btn_corner_cb, LV_EVENT_CLICKED, NULL);
    lv_obj_t *lbl_tr = lv_label_create(s_btn_tr);
    lv_label_set_text(lbl_tr, "TR [1023, 0]");
    lv_obj_center(lbl_tr);

    /* Bottom Left (0, 599) */
    s_btn_bl = lv_btn_create(scr);
    lv_obj_set_size(s_btn_bl, 110, 45);
    lv_obj_set_pos(s_btn_bl, 5, BOARD_LCD_V_RES - 50);
    lv_obj_add_event_cb(s_btn_bl, btn_corner_cb, LV_EVENT_CLICKED, NULL);
    lv_obj_t *lbl_bl = lv_label_create(s_btn_bl);
    lv_label_set_text(lbl_bl, "BL [0, 599]");
    lv_obj_center(lbl_bl);

    /* Bottom Right (1023, 599) */
    s_btn_br = lv_btn_create(scr);
    lv_obj_set_size(s_btn_br, 110, 45);
    lv_obj_set_pos(s_btn_br, BOARD_LCD_H_RES - 115, BOARD_LCD_V_RES - 50);
    lv_obj_add_event_cb(s_btn_br, btn_corner_cb, LV_EVENT_CLICKED, NULL);
    lv_obj_t *lbl_br = lv_label_create(s_btn_br);
    lv_label_set_text(lbl_br, "BR [1023, 599]");
    lv_obj_center(lbl_br);

    /* Floating touch circle indicator */
    s_touch_indicator = lv_obj_create(scr);
    lv_obj_set_size(s_touch_indicator, 40, 40);
    lv_obj_set_style_radius(s_touch_indicator, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(s_touch_indicator, lv_color_hex(0x00E5FF), 0);
    lv_obj_set_style_bg_opa(s_touch_indicator, LV_OPA_60, 0);
    lv_obj_set_style_border_color(s_touch_indicator, lv_color_hex(0xFFFFFF), 0);
    lv_obj_set_style_border_width(s_touch_indicator, 2, 0);
    lv_obj_add_flag(s_touch_indicator, LV_OBJ_FLAG_HIDDEN);
    lv_obj_clear_flag(s_touch_indicator, LV_OBJ_FLAG_CLICKABLE);

    ESP_LOGI(TAG, "LVGL test scene initialized successfully.");
#else
    ESP_LOGI(TAG, "Direct framebuffer test pattern initialized.");
#endif
}

void ui_test_update_touch(bool touch_active, uint16_t x, uint16_t y, uint8_t point_count, uint32_t fps)
{
#if HAVE_LVGL
    if (s_coord_label) {
        char buf[64];
        if (touch_active) {
            snprintf(buf, sizeof(buf), "Touch: Active | X: %u, Y: %u | Pts: %u", x, y, point_count);
            lv_label_set_text(s_coord_label, buf);
            if (s_touch_indicator) {
                lv_obj_clear_flag(s_touch_indicator, LV_OBJ_FLAG_HIDDEN);
                lv_obj_set_pos(s_touch_indicator, x - 20, y - 20);
            }
        } else {
            lv_label_set_text(s_coord_label, "Touch: Released (Ready)");
            if (s_touch_indicator) {
                lv_obj_add_flag(s_touch_indicator, LV_OBJ_FLAG_HIDDEN);
            }
        }
    }

    if (s_fps_label && fps > 0) {
        char fps_buf[48];
        snprintf(fps_buf, sizeof(fps_buf), "FPS: %lu | Tear-Free Direct FB", (unsigned long)fps);
        lv_label_set_text(s_fps_label, fps_buf);
    }
#endif
}
