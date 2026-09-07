#include <stdio.h>
#include <stdbool.h>
#include <SDL.h>
#include "lvgl.h"
#include "board_config.h"
#include "ui_test.h"

#define SIM_WIDTH  BOARD_LCD_H_RES
#define SIM_HEIGHT BOARD_LCD_V_RES

static SDL_Window *s_window = NULL;
static SDL_Renderer *s_renderer = NULL;
static SDL_Texture *s_texture = NULL;
static uint32_t s_pixel_buffer[SIM_WIDTH * SIM_HEIGHT];

static bool s_mouse_down = false;
static int s_mouse_x = 0;
static int s_mouse_y = 0;

static void sdl_disp_flush(lv_disp_drv_t *disp_drv, const lv_area_t *area, lv_color_t *color_p)
{
    int32_t w = lv_area_get_width(area);
    int32_t h = lv_area_get_height(area);

    for (int y = 0; y < h; y++) {
        for (int x = 0; x < w; x++) {
            int px = area->x1 + x;
            int py = area->y1 + y;
            if (px >= 0 && px < SIM_WIDTH && py >= 0 && py < SIM_HEIGHT) {
                lv_color_t c = color_p[y * w + x];
                /* Convert LVGL color to 32-bit ARGB */
                uint32_t argb = lv_color_to32(c);
                s_pixel_buffer[py * SIM_WIDTH + px] = argb;
            }
        }
    }

    lv_disp_flush_ready(disp_drv);
}

static void sdl_mouse_read(lv_indev_drv_t *indev_drv, lv_indev_data_t *data)
{
    (void)indev_drv;
    data->point.x = s_mouse_x;
    data->point.y = s_mouse_y;
    data->state = s_mouse_down ? LV_INDEV_STATE_PRESSED : LV_INDEV_STATE_RELEASED;
}

int main(int argc, char *argv[])
{
    (void)argc;
    (void)argv;

    printf("===============================================================\n");
    printf(" Waveshare ESP32-S3-Touch-LCD-7B Native macOS SDL2 Simulator   \n");
    printf(" Resolution: %dx%d (Exact C codebase)\n", SIM_WIDTH, SIM_HEIGHT);
    printf("===============================================================\n");

    if (SDL_Init(SDL_INIT_VIDEO) != 0) {
        fprintf(stderr, "SDL_Init failed: %s\n", SDL_GetError());
        return 1;
    }

    s_window = SDL_CreateWindow(
        "Waveshare ESP32-S3-Touch-LCD-7B (Native C / LVGL Simulator)",
        SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
        SIM_WIDTH, SIM_HEIGHT,
        SDL_WINDOW_SHOWN | SDL_WINDOW_ALLOW_HIGHDPI
    );

    if (!s_window) {
        fprintf(stderr, "SDL_CreateWindow failed: %s\n", SDL_GetError());
        SDL_Quit();
        return 1;
    }

    s_renderer = SDL_CreateRenderer(s_window, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);
    if (!s_renderer) {
        s_renderer = SDL_CreateRenderer(s_window, -1, 0);
    }

    s_texture = SDL_CreateTexture(
        s_renderer,
        SDL_PIXELFORMAT_ARGB8888,
        SDL_TEXTUREACCESS_STREAMING,
        SIM_WIDTH, SIM_HEIGHT
    );

    /* Initialize LVGL */
    lv_init();

    /* Double buffer for LVGL */
    static lv_color_t buf1[SIM_WIDTH * 40];
    static lv_color_t buf2[SIM_WIDTH * 40];
    static lv_disp_draw_buf_t disp_buf;
    lv_disp_draw_buf_init(&disp_buf, buf1, buf2, SIM_WIDTH * 40);

    static lv_disp_drv_t disp_drv;
    lv_disp_drv_init(&disp_drv);
    disp_drv.hor_res = SIM_WIDTH;
    disp_drv.ver_res = SIM_HEIGHT;
    disp_drv.flush_cb = sdl_disp_flush;
    disp_drv.draw_buf = &disp_buf;
    lv_disp_drv_register(&disp_drv);

    /* Register Mouse as Touch Input */
    static lv_indev_drv_t indev_drv;
    lv_indev_drv_init(&indev_drv);
    indev_drv.type = LV_INDEV_TYPE_POINTER;
    indev_drv.read_cb = sdl_mouse_read;
    lv_indev_drv_register(&indev_drv);

    /* Initialize exact C test scene */
    ui_test_init();

    bool running = true;
    uint32_t last_time = SDL_GetTicks();
    uint32_t frame_count = 0;
    uint32_t last_fps_time = last_time;
    uint32_t current_fps = 60;

    while (running) {
        SDL_Event event;
        while (SDL_PollEvent(&event)) {
            if (event.type == SDL_QUIT) {
                running = false;
            } else if (event.type == SDL_MOUSEBUTTONDOWN) {
                if (event.button.button == SDL_BUTTON_LEFT) {
                    s_mouse_down = true;
                    s_mouse_x = event.button.x;
                    s_mouse_y = event.button.y;
                }
            } else if (event.type == SDL_MOUSEBUTTONUP) {
                if (event.button.button == SDL_BUTTON_LEFT) {
                    s_mouse_down = false;
                }
            } else if (event.type == SDL_MOUSEMOTION) {
                s_mouse_x = event.motion.x;
                s_mouse_y = event.motion.y;
            }
        }

        uint32_t now = SDL_GetTicks();
        lv_timer_handler();

        frame_count++;
        if (now - last_fps_time >= 1000) {
            current_fps = (frame_count * 1000) / (now - last_fps_time);
            frame_count = 0;
            last_fps_time = now;
        }

        ui_test_update_touch(s_mouse_down, (uint16_t)s_mouse_x, (uint16_t)s_mouse_y, s_mouse_down ? 1 : 0, current_fps);

        /* Update texture and render */
        SDL_UpdateTexture(s_texture, NULL, s_pixel_buffer, SIM_WIDTH * sizeof(uint32_t));
        SDL_RenderClear(s_renderer);
        SDL_RenderCopy(s_renderer, s_texture, NULL, NULL);
        SDL_RenderPresent(s_renderer);

        SDL_Delay(10);
    }

    SDL_DestroyTexture(s_texture);
    SDL_DestroyRenderer(s_renderer);
    SDL_DestroyWindow(s_window);
    SDL_Quit();

    return 0;
}
