#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "driver/gpio.h"
#include "driver/i2c.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ========================================================================= */
/* Board Model & Identification                                              */
/* ========================================================================= */
#if defined(WAVESHARE_TOUCH_LCD_7A)
    #define BOARD_NAME                  "Waveshare ESP32-S3-Touch-LCD-7A"
    #define BOARD_LCD_H_RES             800
    #define BOARD_LCD_V_RES             480
    #define BOARD_LCD_PIXEL_CLOCK_HZ    (16 * 1000 * 1000)
    #define BOARD_LCD_HSYNC_PULSE_WIDTH 40
    #define BOARD_LCD_HSYNC_BACK_PORCH  40
    #define BOARD_LCD_HSYNC_FRONT_PORCH 48
    #define BOARD_LCD_VSYNC_PULSE_WIDTH 13
    #define BOARD_LCD_VSYNC_BACK_PORCH  31
    #define BOARD_LCD_VSYNC_FRONT_PORCH 13
#else
    /* Default: Waveshare ESP32-S3-Touch-LCD-7B (1024x600 IPS) */
    #define BOARD_NAME                  "Waveshare ESP32-S3-Touch-LCD-7B"
    #define BOARD_LCD_H_RES             1024
    #define BOARD_LCD_V_RES             600
    #define BOARD_LCD_PIXEL_CLOCK_HZ    (16 * 1000 * 1000)
    #define BOARD_LCD_HSYNC_PULSE_WIDTH 20
    #define BOARD_LCD_HSYNC_BACK_PORCH  140
    #define BOARD_LCD_HSYNC_FRONT_PORCH 160
    #define BOARD_LCD_VSYNC_PULSE_WIDTH 3
    #define BOARD_LCD_VSYNC_BACK_PORCH  12
    #define BOARD_LCD_VSYNC_FRONT_PORCH 12
#endif

/* ========================================================================= */
/* RGB LCD Interface Pinout (16-bit RGB565)                                  */
/* ========================================================================= */
#define BOARD_LCD_PIN_PCLK              GPIO_NUM_8
#define BOARD_LCD_PIN_VSYNC             GPIO_NUM_3
#define BOARD_LCD_PIN_HSYNC             GPIO_NUM_46
#define BOARD_LCD_PIN_DE                GPIO_NUM_9
#define BOARD_LCD_PIN_DISP_EN           GPIO_NUM_NC

/* Red Pins (R0..R4) */
#define BOARD_LCD_PIN_DATA0             GPIO_NUM_1   /* R0 */
#define BOARD_LCD_PIN_DATA1             GPIO_NUM_2   /* R1 */
#define BOARD_LCD_PIN_DATA2             GPIO_NUM_42  /* R2 */
#define BOARD_LCD_PIN_DATA3             GPIO_NUM_41  /* R3 */
#define BOARD_LCD_PIN_DATA4             GPIO_NUM_40  /* R4 */

/* Green Pins (G0..G5) */
#define BOARD_LCD_PIN_DATA5             GPIO_NUM_39  /* G0 */
#define BOARD_LCD_PIN_DATA6             GPIO_NUM_0   /* G1 */
#define BOARD_LCD_PIN_DATA7             GPIO_NUM_45  /* G2 */
#define BOARD_LCD_PIN_DATA8             GPIO_NUM_48  /* G3 */
#define BOARD_LCD_PIN_DATA9             GPIO_NUM_47  /* G4 */
#define BOARD_LCD_PIN_DATA10            GPIO_NUM_21  /* G5 */

/* Blue Pins (B0..B4) */
#define BOARD_LCD_PIN_DATA11            GPIO_NUM_14  /* B0 */
#define BOARD_LCD_PIN_DATA12            GPIO_NUM_38  /* B1 */
#define BOARD_LCD_PIN_DATA13            GPIO_NUM_18  /* B2 */
#define BOARD_LCD_PIN_DATA14            GPIO_NUM_17  /* B3 */
#define BOARD_LCD_PIN_DATA15            GPIO_NUM_10  /* B4 */

/* LCD Timing & Signal Flags */
#define BOARD_LCD_FLAGS_PCLK_ACTIVE_NEG 1
#define BOARD_LCD_FLAGS_DE_IDLE_HIGH    0
#define BOARD_LCD_FLAGS_PCLK_IDLE_HIGH  0

/* Frame Buffer & Rendering Configuration */
#define BOARD_LCD_NUM_FB                2             /* Double buffering */
#define BOARD_LCD_BOUNCE_BUFFER_PX      (BOARD_LCD_H_RES * 10)

/* ========================================================================= */
/* Touch & I2C Interface (GT911)                                             */
/* ========================================================================= */
#define BOARD_I2C_PORT                  I2C_NUM_0
#define BOARD_I2C_PIN_SDA               GPIO_NUM_19
#define BOARD_I2C_PIN_SCL               GPIO_NUM_20
#define BOARD_I2C_FREQ_HZ               400000

#define BOARD_TOUCH_GT911_ADDR_PRIMARY   0x5D
#define BOARD_TOUCH_GT911_ADDR_SECONDARY 0x14
#define BOARD_TOUCH_PIN_INT             GPIO_NUM_11
#define BOARD_TOUCH_PIN_RST             GPIO_NUM_4
#define BOARD_TOUCH_MAX_POINTS          5

/* ========================================================================= */
/* Backlight Control                                                         */
/* ========================================================================= */
#define BOARD_BACKLIGHT_PIN             GPIO_NUM_6
#define BOARD_BACKLIGHT_PWM_FREQ_HZ     5000
#define BOARD_BACKLIGHT_DEFAULT_PERCENT 85

/* ========================================================================= */
/* I2C IO Expander (CH422G / PCA9554)                                        */
/* ========================================================================= */
#define BOARD_EXPANDER_CH422G_ADDR      0x24
#define BOARD_EXPANDER_PCA9554_ADDR     0x20

#define BOARD_EXP_PIN_TP_RST            1
#define BOARD_EXP_PIN_LCD_RST           2
#define BOARD_EXP_PIN_LCD_BL            3
#define BOARD_EXP_PIN_SD_CS             4

#ifdef __cplusplus
}
#endif
