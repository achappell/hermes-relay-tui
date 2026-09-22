#include "ui_display.h"

#include "board_config.h"
#ifdef ESP_PLATFORM
#include "sdkconfig.h"
#ifdef CONFIG_TOUCH_VOICE
#include "touch_capture.h"
#endif
#endif

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

static display_rules_reducer_t s_reducer;
static ui_snapshot_t s_snapshot;
static display_rules_snapshot_t s_rules_snapshot;

static display_rules_result_t apply_snapshot_model(const ui_snapshot_t *snapshot)
{
    if (snapshot == NULL) return DISPLAY_RULES_INVALID_ARGUMENT;
    if (!ui_snapshot_to_rules(snapshot, &s_rules_snapshot)) {
        return DISPLAY_RULES_INVALID_SNAPSHOT;
    }
    display_rules_result_t result = display_rules_apply_snapshot(&s_reducer, &s_rules_snapshot);
    if (result != DISPLAY_RULES_ACCEPTED) return result;
    s_snapshot = *snapshot;
    return result;
}

#if HAVE_LVGL
static lv_obj_t *s_state_label;
static lv_obj_t *s_status_label;
static lv_obj_t *s_account_label;
static lv_obj_t *s_response_label;
static lv_obj_t *s_prompt_panel;
static lv_obj_t *s_prompt_title;
static lv_obj_t *s_prompt_body;
static lv_obj_t *s_prompt_buttons[UI_SNAPSHOT_OPTION_COUNT_MAX];
static lv_obj_t *s_choice_list;
static lv_obj_t *s_choice_choose_button;
static lv_obj_t *s_choice_explore_button;
static lv_obj_t *s_diagnostics_label;
static ui_display_action_cb s_action_cb;
static void *s_action_user_data;
static int16_t s_selected_choice = -1;
static char s_selected_action_id[UI_SNAPSHOT_ACTION_ID_MAX];
static char s_selected_object_id[UI_SNAPSHOT_CHOICE_CONTEXT_MAX];
static char s_selected_freshness[UI_SNAPSHOT_CHOICE_CONTEXT_MAX];

static void render_prompt(void);

static void copy_prompt_key(char *destination, size_t capacity, const char *source)
{
    if (destination == NULL || capacity == 0 || source == NULL) return;
    size_t length = strlen(source);
    if (length >= capacity) length = capacity - 1;
    memcpy(destination, source, length);
    destination[length] = '\0';
}

static lv_color_t state_color(ui_display_state_t state)
{
    switch (state) {
        case UI_DISPLAY_ERROR: return lv_color_hex(0xFF6B6B);
        case UI_DISPLAY_SPEAKING: return lv_color_hex(0x69F0AE);
        case UI_DISPLAY_LISTENING:
        case UI_DISPLAY_HEARD: return lv_color_hex(0xFFD54F);
        case UI_DISPLAY_THINKING:
        case UI_DISPLAY_BUFFERING: return lv_color_hex(0x80CBC4);
        case UI_DISPLAY_DISCONNECTED: return lv_color_hex(0xB0BEC5);
        default: return lv_color_hex(0xEDE7F6);
    }
}

static void prompt_button_cb(lv_event_t *event)
{
    if (s_action_cb == NULL) return;
    lv_obj_t *button = lv_event_get_target(event);
    for (uint8_t index = 0; index < s_snapshot.prompt.option_count; index++) {
        if (button == s_prompt_buttons[index]) {
            if (s_snapshot.prompt.typed_choice) {
                s_selected_choice = (int16_t)index;
                render_prompt();
                return;
            }
            const char *action_id = s_snapshot.prompt.action_id;
            const char *choice = s_snapshot.prompt.options[index].id;
            if (ui_display_validate_choice(action_id, choice) == DISPLAY_RULES_ACCEPTED) {
                s_action_cb(action_id, choice, NULL, NULL, NULL, s_action_user_data);
            }
            return;
        }
    }
}

static void typed_choice_action_cb(lv_event_t *event)
{
    if (s_action_cb == NULL || s_selected_choice < 0 ||
        s_selected_choice >= s_snapshot.prompt.option_count) {
        return;
    }
    const char *operation = (const char *)lv_event_get_user_data(event);
    const ui_snapshot_prompt_t *prompt = &s_snapshot.prompt;
    const char *option_id = prompt->options[s_selected_choice].id;
    if (ui_display_validate_typed_choice(
            prompt->action_id,
            operation,
            option_id,
            prompt->object_id,
            prompt->freshness) == DISPLAY_RULES_ACCEPTED) {
        s_action_cb(
            prompt->action_id,
            option_id,
            operation,
            prompt->object_id,
            prompt->freshness,
            s_action_user_data);
    }
}

static lv_obj_t *make_label(lv_obj_t *parent, const char *text, lv_color_t color)
{
    lv_obj_t *label = lv_label_create(parent);
    lv_label_set_text(label, text);
    lv_obj_set_style_text_color(label, color, 0);
    return label;
}

static void render_prompt(void)
{
#ifdef CONFIG_TOUCH_VOICE
    lv_obj_add_flag(s_prompt_panel, LV_OBJ_FLAG_HIDDEN);
    return;
#endif
    if (!s_prompt_panel) return;
    if (!s_snapshot.prompt.present) {
        lv_obj_add_flag(s_prompt_panel, LV_OBJ_FLAG_HIDDEN);
        return;
    }

    const ui_snapshot_prompt_t *prompt = &s_snapshot.prompt;
    lv_obj_clear_flag(s_prompt_panel, LV_OBJ_FLAG_HIDDEN);
    lv_label_set_text(s_prompt_title, s_snapshot.prompt.title);
    lv_label_set_text(s_prompt_body, s_snapshot.prompt.body);
    const display_rules_view_t *view = ui_display_rules_view();
    if (s_snapshot.prompt.typed_choice) {
        if (strcmp(s_selected_action_id, prompt->action_id) != 0 ||
            strcmp(s_selected_object_id, prompt->object_id) != 0 ||
            strcmp(s_selected_freshness, prompt->freshness) != 0) {
            s_selected_choice = -1;
            copy_prompt_key(s_selected_action_id, sizeof(s_selected_action_id), prompt->action_id);
            copy_prompt_key(s_selected_object_id, sizeof(s_selected_object_id), prompt->object_id);
            copy_prompt_key(s_selected_freshness, sizeof(s_selected_freshness), prompt->freshness);
        }
        if (s_selected_choice >= prompt->option_count) s_selected_choice = -1;
        lv_obj_set_size(s_prompt_panel, BOARD_LCD_H_RES - 120, BOARD_LCD_V_RES - 100);
        lv_obj_center(s_prompt_panel);
        lv_label_set_long_mode(s_prompt_body, LV_LABEL_LONG_SCROLL);
        lv_obj_set_width(s_prompt_body, BOARD_LCD_H_RES - 170);
        lv_obj_set_height(s_prompt_body, 72);
        lv_obj_set_pos(s_prompt_body, 20, 58);
        lv_obj_clear_flag(s_choice_list, LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_size(s_choice_list, BOARD_LCD_H_RES - 168, 264);
        lv_obj_set_pos(s_choice_list, 24, 142);
        for (uint8_t index = 0; index < UI_SNAPSHOT_OPTION_COUNT_MAX; index++) {
            lv_obj_t *button = s_prompt_buttons[index];
            if (lv_obj_get_parent(button) != s_choice_list) {
                lv_obj_set_parent(button, s_choice_list);
            }
            if (index < prompt->option_count) {
                lv_obj_clear_flag(button, LV_OBJ_FLAG_HIDDEN);
                lv_obj_clear_state(button, LV_STATE_DISABLED);
                if (index == s_selected_choice) {
                    lv_obj_add_state(button, LV_STATE_CHECKED);
                } else {
                    lv_obj_clear_state(button, LV_STATE_CHECKED);
                }
                lv_obj_set_size(button, BOARD_LCD_H_RES - 192, 46);
                lv_obj_set_pos(button, 4, (lv_coord_t)(index * 52));
                lv_label_set_text(lv_obj_get_child(button, 0), prompt->options[index].label);
                lv_obj_set_width(lv_obj_get_child(button, 0), BOARD_LCD_H_RES - 224);
                lv_label_set_long_mode(lv_obj_get_child(button, 0), LV_LABEL_LONG_DOT);
            } else {
                lv_obj_add_flag(button, LV_OBJ_FLAG_HIDDEN);
            }
        }
        if (view != NULL && view->can_choose) {
            lv_obj_clear_flag(s_choice_choose_button, LV_OBJ_FLAG_HIDDEN);
            lv_obj_clear_state(s_choice_choose_button, LV_STATE_DISABLED);
        } else {
            lv_obj_add_flag(s_choice_choose_button, LV_OBJ_FLAG_HIDDEN);
        }
        if (view != NULL && view->can_explore) {
            lv_obj_clear_flag(s_choice_explore_button, LV_OBJ_FLAG_HIDDEN);
            lv_obj_clear_state(s_choice_explore_button, LV_STATE_DISABLED);
        } else {
            lv_obj_add_flag(s_choice_explore_button, LV_OBJ_FLAG_HIDDEN);
        }
        if (s_selected_choice < 0) {
            lv_obj_add_state(s_choice_choose_button, LV_STATE_DISABLED);
            lv_obj_add_state(s_choice_explore_button, LV_STATE_DISABLED);
        } else {
            if (view != NULL && view->can_choose) {
                lv_obj_clear_state(s_choice_choose_button, LV_STATE_DISABLED);
            }
            if (view != NULL && view->can_explore) {
                lv_obj_clear_state(s_choice_explore_button, LV_STATE_DISABLED);
            }
        }
        return;
    }

    s_selected_choice = -1;
    s_selected_action_id[0] = '\0';
    s_selected_object_id[0] = '\0';
    s_selected_freshness[0] = '\0';
    lv_obj_set_size(s_prompt_panel, BOARD_LCD_H_RES - 220, 270);
    lv_obj_center(s_prompt_panel);
    lv_label_set_long_mode(s_prompt_body, LV_LABEL_LONG_DOT);
    lv_obj_set_width(s_prompt_body, BOARD_LCD_H_RES - 280);
    lv_obj_set_height(s_prompt_body, LV_SIZE_CONTENT);
    lv_obj_set_pos(s_prompt_body, 20, 58);
    lv_obj_add_flag(s_choice_list, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(s_choice_choose_button, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(s_choice_explore_button, LV_OBJ_FLAG_HIDDEN);
    for (uint8_t index = 0; index < UI_SNAPSHOT_OPTION_COUNT_MAX; index++) {
        lv_obj_t *button = s_prompt_buttons[index];
        if (lv_obj_get_parent(button) != s_prompt_panel) {
            lv_obj_set_parent(button, s_prompt_panel);
        }
        if (index < prompt->option_count && index < UI_SNAPSHOT_GENERIC_OPTION_COUNT_MAX) {
            lv_obj_clear_flag(button, LV_OBJ_FLAG_HIDDEN);
            if (view != NULL && view->can_choose) {
                lv_obj_clear_state(button, LV_STATE_DISABLED);
            } else {
                lv_obj_add_state(button, LV_STATE_DISABLED);
            }
            lv_obj_clear_state(button, LV_STATE_CHECKED);
            lv_obj_set_size(button, 140, 46);
            lv_obj_set_pos(button, 20 + (index % 2) * 160, 150 + (index / 2) * 56);
            lv_label_set_text(lv_obj_get_child(button, 0), prompt->options[index].label);
        } else {
            lv_obj_add_flag(button, LV_OBJ_FLAG_HIDDEN);
        }
    }
}

static void render_snapshot(void)
{
    const display_rules_view_t *view = ui_display_rules_view();
    ui_display_state_t state = view == NULL ? UI_DISPLAY_UNKNOWN : view->state;
    lv_label_set_text(s_state_label, ui_display_state_name(state));
    lv_obj_set_style_text_color(s_state_label, state_color(state), 0);
    lv_label_set_text(s_status_label, s_snapshot.status_text[0] ? s_snapshot.status_text : "Ready");
    lv_label_set_text(s_account_label, s_snapshot.account[0] ? s_snapshot.account : "Hermes home display");
    lv_label_set_text(s_response_label, s_snapshot.response_text[0] ? s_snapshot.response_text : "Ask me anything");
    render_prompt();
}

bool ui_display_init(ui_display_action_cb action_cb, void *user_data)
{
    display_rules_init(&s_reducer);
    s_action_cb = action_cb;
    s_action_user_data = user_data;
    ui_snapshot_init(&s_snapshot);

    lv_obj_t *screen = lv_scr_act();
    lv_obj_set_style_bg_color(screen, lv_color_hex(0x121214), 0);

    lv_obj_t *header = lv_obj_create(screen);
    lv_obj_set_size(header, BOARD_LCD_H_RES, 82);
    lv_obj_set_pos(header, 0, 0);
    lv_obj_set_style_bg_color(header, lv_color_hex(0x1E1E24), 0);
    lv_obj_set_style_radius(header, 0, 0);
    lv_obj_clear_flag(header, LV_OBJ_FLAG_SCROLLABLE);

    s_state_label = make_label(header, "idle", lv_color_hex(0xEDE7F6));
    lv_obj_set_style_text_font(s_state_label, LV_FONT_DEFAULT, 0);
    lv_obj_align(s_state_label, LV_ALIGN_LEFT_MID, 24, -10);
    s_status_label = make_label(header, "Ready", lv_color_hex(0xB0BEC5));
    lv_obj_align(s_status_label, LV_ALIGN_LEFT_MID, 24, 23);
    s_account_label = make_label(header, "Hermes home display", lv_color_hex(0xB0BEC5));
    lv_obj_align(s_account_label, LV_ALIGN_RIGHT_MID, -24, 0);

    lv_obj_t *response_panel = lv_obj_create(screen);
    lv_obj_set_size(response_panel, BOARD_LCD_H_RES - 96, 300);
    lv_obj_set_pos(response_panel, 48, 112);
    lv_obj_set_style_bg_color(response_panel, lv_color_hex(0x18181E), 0);
    lv_obj_set_style_border_color(response_panel, lv_color_hex(0x2E2E38), 0);
    s_response_label = make_label(response_panel, "Ask me anything", lv_color_hex(0xF5F5F5));
    lv_obj_set_width(s_response_label, BOARD_LCD_H_RES - 140);
    lv_label_set_long_mode(s_response_label, LV_LABEL_LONG_SCROLL_CIRCULAR);
    lv_obj_align(s_response_label, LV_ALIGN_TOP_LEFT, 20, 24);

    s_prompt_panel = lv_obj_create(screen);
    lv_obj_set_size(s_prompt_panel, BOARD_LCD_H_RES - 220, 270);
    lv_obj_center(s_prompt_panel);
    lv_obj_set_style_bg_color(s_prompt_panel, lv_color_hex(0x292936), 0);
    lv_obj_clear_flag(s_prompt_panel, LV_OBJ_FLAG_SCROLLABLE);
    s_prompt_title = make_label(s_prompt_panel, "Prompt", lv_color_hex(0xFFFFFF));
    lv_obj_align(s_prompt_title, LV_ALIGN_TOP_LEFT, 20, 18);
    s_prompt_body = make_label(s_prompt_panel, "", lv_color_hex(0xE0E0E0));
    lv_obj_set_width(s_prompt_body, BOARD_LCD_H_RES - 280);
    lv_obj_set_height(s_prompt_body, LV_SIZE_CONTENT);
    lv_label_set_long_mode(s_prompt_body, LV_LABEL_LONG_DOT);
    lv_obj_align(s_prompt_body, LV_ALIGN_TOP_LEFT, 20, 58);
    s_choice_list = lv_obj_create(s_prompt_panel);
    lv_obj_set_style_bg_opa(s_choice_list, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(s_choice_list, 0, 0);
    lv_obj_set_style_pad_all(s_choice_list, 4, 0);
    lv_obj_set_scroll_dir(s_choice_list, LV_DIR_VER);
    lv_obj_set_scrollbar_mode(s_choice_list, LV_SCROLLBAR_MODE_AUTO);
    lv_obj_add_flag(s_choice_list, LV_OBJ_FLAG_HIDDEN);
    for (uint8_t index = 0; index < UI_SNAPSHOT_OPTION_COUNT_MAX; index++) {
        s_prompt_buttons[index] = lv_btn_create(s_prompt_panel);
        lv_obj_add_flag(s_prompt_buttons[index], LV_OBJ_FLAG_CHECKABLE);
        lv_obj_set_size(s_prompt_buttons[index], 140, 46);
        lv_obj_set_pos(s_prompt_buttons[index], 20 + (index % 2) * 160, 150 + (index / 2) * 56);
        lv_obj_add_event_cb(s_prompt_buttons[index], prompt_button_cb, LV_EVENT_CLICKED, NULL);
        lv_obj_t *label = lv_label_create(s_prompt_buttons[index]);
        lv_label_set_text(label, "Option");
        lv_obj_center(label);
        if (index >= UI_SNAPSHOT_GENERIC_OPTION_COUNT_MAX) {
            lv_obj_add_flag(s_prompt_buttons[index], LV_OBJ_FLAG_HIDDEN);
        }
    }
    s_choice_choose_button = lv_btn_create(s_prompt_panel);
    lv_obj_set_size(s_choice_choose_button, 190, 52);
    lv_obj_set_pos(s_choice_choose_button, 230, BOARD_LCD_V_RES - 178);
    lv_obj_add_event_cb(s_choice_choose_button, typed_choice_action_cb, LV_EVENT_CLICKED, "choose");
    lv_obj_t *choose_label = lv_label_create(s_choice_choose_button);
    lv_label_set_text(choose_label, "Choose");
    lv_obj_center(choose_label);
    lv_obj_add_flag(s_choice_choose_button, LV_OBJ_FLAG_HIDDEN);
    s_choice_explore_button = lv_btn_create(s_prompt_panel);
    lv_obj_set_size(s_choice_explore_button, 190, 52);
    lv_obj_set_pos(s_choice_explore_button, 450, BOARD_LCD_V_RES - 178);
    lv_obj_add_event_cb(s_choice_explore_button, typed_choice_action_cb, LV_EVENT_CLICKED, "explore");
    lv_obj_t *explore_label = lv_label_create(s_choice_explore_button);
    lv_label_set_text(explore_label, "Explore");
    lv_obj_center(explore_label);
    lv_obj_add_flag(s_choice_explore_button, LV_OBJ_FLAG_HIDDEN);

    s_diagnostics_label = make_label(screen, "Touch: idle | FPS: --", lv_color_hex(0x78909C));
    lv_obj_align(s_diagnostics_label, LV_ALIGN_BOTTOM_LEFT, 48, -20);
    render_snapshot();
    return true;
}

display_rules_result_t ui_display_set_snapshot(const ui_snapshot_t *snapshot)
{
    display_rules_result_t result = apply_snapshot_model(snapshot);
    if (result != DISPLAY_RULES_ACCEPTED) return result;
    render_snapshot();
    return result;
}

void ui_display_update_diagnostics(bool touch_active, uint16_t x, uint16_t y, uint8_t point_count, uint32_t fps)
{
    if (!s_diagnostics_label) return;
    char text[96];
    if (touch_active) {
        lv_snprintf(text, sizeof(text), "Touch: %u,%u (%u) | FPS: %lu", x, y, point_count, (unsigned long)fps);
    } else {
        lv_snprintf(text, sizeof(text), "Touch: idle | FPS: %lu", (unsigned long)fps);
    }
    lv_label_set_text(s_diagnostics_label, text);
}
#else
bool ui_display_init(ui_display_action_cb action_cb, void *user_data)
{
    display_rules_init(&s_reducer);
    (void)action_cb;
    (void)user_data;
    return true;
}

display_rules_result_t ui_display_set_snapshot(const ui_snapshot_t *snapshot)
{
    return apply_snapshot_model(snapshot);
}

void ui_display_update_diagnostics(bool touch_active, uint16_t x, uint16_t y, uint8_t point_count, uint32_t fps)
{
    (void)touch_active;
    (void)x;
    (void)y;
    (void)point_count;
    (void)fps;
}
#endif

display_rules_result_t ui_display_set_connection_state(ui_display_connection_state_t state)
{
    if (state == UI_DISPLAY_CONNECTION_CONNECTED) {
        display_rules_init(&s_reducer);
        ui_snapshot_init(&s_snapshot);
#if HAVE_LVGL
        render_snapshot();
#endif
        return DISPLAY_RULES_ACCEPTED;
    }

    static ui_snapshot_t snapshot;
    if (!ui_snapshot_init(&snapshot)) return DISPLAY_RULES_INVALID_ARGUMENT;
    const display_rules_view_t *view = ui_display_rules_view();
    snapshot.sequence = view != NULL && view->initialized ? view->sequence + 1 : 0;
    snapshot.state = state == UI_DISPLAY_CONNECTION_ERROR ? UI_DISPLAY_ERROR : UI_DISPLAY_DISCONNECTED;
    if (!ui_snapshot_set_text(
            &snapshot,
            "",
            state == UI_DISPLAY_CONNECTION_ERROR ? "Display connection error" : "Reconnecting to display")) {
        return DISPLAY_RULES_INVALID_ARGUMENT;
    }
    return ui_display_set_snapshot(&snapshot);
}

display_rules_result_t ui_display_validate_choice(const char *action_id, const char *choice)
{
    return display_rules_validate_choice(&s_reducer, action_id, choice);
}

display_rules_result_t ui_display_validate_typed_choice(
    const char *action_id,
    const char *operation,
    const char *option_id,
    const char *object_id,
    const char *freshness
)
{
    return display_rules_validate_typed_choice(
        &s_reducer, action_id, operation, option_id, object_id, freshness);
}

display_rules_result_t ui_display_validate_dismiss(void)
{
    return display_rules_validate_dismiss(&s_reducer);
}

const display_rules_view_t *ui_display_rules_view(void)
{
    return display_rules_view(&s_reducer);
}

#if HAVE_LVGL && defined(CONFIG_TOUCH_VOICE)
static lv_obj_t *capture_buttons[3], *capture_label;
static void capture_click(lv_event_t *event)
{
    touch_command_t command = (touch_command_t)(uintptr_t)lv_event_get_user_data(event);
    /* Disable immediately: repeated LVGL events cannot queue another Finish. */
    for (int i=0;i<3;i++) lv_obj_add_state(capture_buttons[i], LV_STATE_DISABLED);
    touch_capture_command(command);
}
void ui_display_capture_update(int phase)
{
    if (!capture_label) {
        const char *names[] = {"Talk", "Finish", "Cancel"};
        for (int i=0;i<3;i++) {
            capture_buttons[i] = lv_btn_create(lv_scr_act());
            lv_obj_set_size(capture_buttons[i], 130, 48);
            lv_obj_align(capture_buttons[i], LV_ALIGN_BOTTOM_MID, (i-1)*150, -40);
            lv_obj_add_event_cb(capture_buttons[i], capture_click, LV_EVENT_CLICKED, (void *)(uintptr_t)i);
            lv_obj_t *label = lv_label_create(capture_buttons[i]);
            lv_label_set_text(label, names[i]);lv_obj_center(label);
        }
        capture_label = lv_label_create(lv_scr_act());
        lv_obj_align(capture_label, LV_ALIGN_BOTTOM_MID, 0, -100);
    }
    lv_label_set_text(capture_label, touch_capture_status());
    bool enabled[] = {phase==TOUCH_IDLE, phase==TOUCH_RECORDING,
        phase==TOUCH_ADMISSION || phase==TOUCH_STARTING || phase==TOUCH_RECORDING};
    for (int i=0;i<3;i++) {
        if(enabled[i]) lv_obj_clear_state(capture_buttons[i], LV_STATE_DISABLED);
        else lv_obj_add_state(capture_buttons[i], LV_STATE_DISABLED);
    }
}
#else
void ui_display_capture_update(int phase) { (void)phase; }
#endif
