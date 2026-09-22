#pragma once
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
typedef uint32_t lv_color_t;
typedef int lv_coord_t;
typedef struct lv_obj {unsigned state;struct lv_obj *parent;} lv_obj_t;
typedef struct {void *data;lv_obj_t *target;} lv_event_t;
#define lv_snprintf snprintf
#define LV_ALIGN_BOTTOM_LEFT 1
#define LV_ALIGN_BOTTOM_MID 2
#define LV_ALIGN_LEFT_MID 4
#define LV_ALIGN_RIGHT_MID 8
#define LV_ALIGN_TOP_LEFT 16
#define LV_DIR_VER 32
#define LV_EVENT_CLICKED 64
#define LV_FONT_DEFAULT 128
#define LV_LABEL_LONG_DOT 256
#define LV_LABEL_LONG_SCROLL 512
#define LV_LABEL_LONG_SCROLL_CIRCULAR 1024
#define LV_OBJ_FLAG_CHECKABLE 2048
#define LV_OBJ_FLAG_HIDDEN 4096
#define LV_OBJ_FLAG_SCROLLABLE 8192
#define LV_OPA_TRANSP 16384
#define LV_SCROLLBAR_MODE_AUTO 32768
#define LV_SIZE_CONTENT 65536
#define LV_STATE_CHECKED 131072
#define LV_STATE_DISABLED 262144
static inline lv_obj_t *lv_obj_create(lv_obj_t *p) {lv_obj_t *o=calloc(1,sizeof(*o));o->parent=p;return o;}
#define lv_label_create lv_obj_create
#define lv_btn_create lv_obj_create
static inline lv_obj_t *lv_scr_act(void) {static lv_obj_t screen;return &screen;}
static inline lv_obj_t *lv_obj_get_parent(lv_obj_t *o) {return o->parent;}
static inline lv_obj_t *lv_obj_get_child(lv_obj_t *o,int index) {(void)index;return o;}
static inline void *lv_event_get_user_data(lv_event_t *e) {return e->data;}
static inline lv_obj_t *lv_event_get_target(lv_event_t *e) {return e->target;}
static inline lv_color_t lv_color_hex(uint32_t c) {return c;}
static inline void lv_obj_add_state(lv_obj_t *o,unsigned s) {o->state|=s;}
static inline void lv_obj_clear_state(lv_obj_t *o,unsigned s) {o->state&=~s;}
static inline void lv_label_set_long_mode(lv_obj_t *o, ...) {(void)o;}
static inline void lv_label_set_text(lv_obj_t *o, ...) {(void)o;}
static inline void lv_obj_add_event_cb(lv_obj_t *o, ...) {(void)o;}
static inline void lv_obj_add_flag(lv_obj_t *o, ...) {(void)o;}
static inline void lv_obj_align(lv_obj_t *o, ...) {(void)o;}
static inline void lv_obj_center(lv_obj_t *o, ...) {(void)o;}
static inline void lv_obj_clear_flag(lv_obj_t *o, ...) {(void)o;}
static inline void lv_obj_set_height(lv_obj_t *o, ...) {(void)o;}
static inline void lv_obj_set_parent(lv_obj_t *o, ...) {(void)o;}
static inline void lv_obj_set_pos(lv_obj_t *o, ...) {(void)o;}
static inline void lv_obj_set_scroll_dir(lv_obj_t *o, ...) {(void)o;}
static inline void lv_obj_set_scrollbar_mode(lv_obj_t *o, ...) {(void)o;}
static inline void lv_obj_set_size(lv_obj_t *o, ...) {(void)o;}
static inline void lv_obj_set_style_bg_color(lv_obj_t *o, ...) {(void)o;}
static inline void lv_obj_set_style_bg_opa(lv_obj_t *o, ...) {(void)o;}
static inline void lv_obj_set_style_border_color(lv_obj_t *o, ...) {(void)o;}
static inline void lv_obj_set_style_border_width(lv_obj_t *o, ...) {(void)o;}
static inline void lv_obj_set_style_pad_all(lv_obj_t *o, ...) {(void)o;}
static inline void lv_obj_set_style_radius(lv_obj_t *o, ...) {(void)o;}
static inline void lv_obj_set_style_text_color(lv_obj_t *o, ...) {(void)o;}
static inline void lv_obj_set_style_text_font(lv_obj_t *o, ...) {(void)o;}
static inline void lv_obj_set_width(lv_obj_t *o, ...) {(void)o;}
