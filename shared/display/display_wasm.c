#include "display_wasm.h"

#include <stddef.h>
#include <string.h>

#if defined(DISPLAY_WASM_WITH_LVGL)
#include "lvgl.h"
#include "ui_display.h"
#endif

static display_rules_reducer_t s_reducer;
static bool s_initialized;

static bool copy_strict(char *destination, size_t capacity, const char *source);

#if defined(DISPLAY_WASM_WITH_LVGL)
static bool s_lvgl_initialized;
static uint32_t s_framebuffer[DISPLAY_WASM_WIDTH * DISPLAY_WASM_HEIGHT];
static lv_color_t s_draw_buffer_a[DISPLAY_WASM_WIDTH * 32];
static lv_color_t s_draw_buffer_b[DISPLAY_WASM_WIDTH * 32];
static int16_t s_pointer_x;
static int16_t s_pointer_y;
static bool s_pointer_pressed;
static lv_timer_t *s_input_read_timer;
static bool s_action_pending;
static char s_action_id[UI_SNAPSHOT_ACTION_ID_MAX];
static char s_action_choice[UI_SNAPSHOT_OPTION_ID_MAX];

static void clear_pending_action(void)
{
    s_action_pending = false;
    s_action_id[0] = '\0';
    s_action_choice[0] = '\0';
}

static void wasm_action_cb(const char *action_id, const char *choice, void *user_data)
{
    (void)user_data;
    if (!copy_strict(s_action_id, sizeof(s_action_id), action_id) ||
        !copy_strict(s_action_choice, sizeof(s_action_choice), choice)) {
        clear_pending_action();
        return;
    }
    s_action_pending = true;
}

static void wasm_touch_read_cb(lv_indev_drv_t *indev_driver, lv_indev_data_t *data)
{
    (void)indev_driver;
    data->point.x = s_pointer_x;
    data->point.y = s_pointer_y;
    data->state = s_pointer_pressed ? LV_INDEV_STATE_PRESSED : LV_INDEV_STATE_RELEASED;
}

static void wasm_flush_cb(
    lv_disp_drv_t *display_driver,
    const lv_area_t *area,
    lv_color_t *color_p
)
{
    int32_t width = lv_area_get_width(area);
    int32_t height = lv_area_get_height(area);
    for (int32_t y = 0; y < height; y++) {
        for (int32_t x = 0; x < width; x++) {
            int32_t pixel_x = area->x1 + x;
            int32_t pixel_y = area->y1 + y;
            if (pixel_x >= 0 && pixel_x < DISPLAY_WASM_WIDTH &&
                pixel_y >= 0 && pixel_y < DISPLAY_WASM_HEIGHT) {
                s_framebuffer[pixel_y * DISPLAY_WASM_WIDTH + pixel_x] =
                    lv_color_to32(color_p[y * width + x]);
            }
        }
    }
    lv_disp_flush_ready(display_driver);
}

static bool init_lvgl(void)
{
    if (s_lvgl_initialized) return true;

    lv_init();
    static lv_disp_draw_buf_t draw_buffer;
    lv_disp_draw_buf_init(
        &draw_buffer,
        s_draw_buffer_a,
        s_draw_buffer_b,
        DISPLAY_WASM_WIDTH * 32);

    static lv_disp_drv_t display_driver;
    lv_disp_drv_init(&display_driver);
    display_driver.hor_res = DISPLAY_WASM_WIDTH;
    display_driver.ver_res = DISPLAY_WASM_HEIGHT;
    display_driver.flush_cb = wasm_flush_cb;
    display_driver.draw_buf = &draw_buffer;
    if (lv_disp_drv_register(&display_driver) == NULL) return false;

    static lv_indev_drv_t input_driver;
    lv_indev_drv_init(&input_driver);
    input_driver.type = LV_INDEV_TYPE_POINTER;
    input_driver.read_cb = wasm_touch_read_cb;
    if (lv_indev_drv_register(&input_driver) == NULL) return false;
    s_input_read_timer = input_driver.read_timer;

    if (!ui_display_init(wasm_action_cb, NULL)) return false;

    s_lvgl_initialized = true;
    return true;
}
#endif

static bool copy_strict(char *destination, size_t capacity, const char *source)
{
    if (destination == NULL || capacity == 0 || source == NULL) return false;
    size_t length = strlen(source);
    if (length >= capacity) return false;
    memcpy(destination, source, length);
    destination[length] = '\0';
    return true;
}

static display_rules_state_t state_from_name(const char *name)
{
    if (name == NULL) return DISPLAY_RULES_UNKNOWN;
    if (strcmp(name, "idle") == 0) return DISPLAY_RULES_IDLE;
    if (strcmp(name, "heard") == 0) return DISPLAY_RULES_HEARD;
    if (strcmp(name, "listening") == 0) return DISPLAY_RULES_LISTENING;
    if (strcmp(name, "thinking") == 0) return DISPLAY_RULES_THINKING;
    if (strcmp(name, "speaking") == 0) return DISPLAY_RULES_SPEAKING;
    if (strcmp(name, "buffering") == 0) return DISPLAY_RULES_BUFFERING;
    if (strcmp(name, "error") == 0) return DISPLAY_RULES_ERROR;
    if (strcmp(name, "disconnected") == 0) return DISPLAY_RULES_DISCONNECTED;
    if (strcmp(name, "prompt") == 0) return DISPLAY_RULES_PROMPT;
    return DISPLAY_RULES_UNKNOWN;
}

static const char *option_id_at(
    uint32_t index,
    const char *option0_id,
    const char *option1_id,
    const char *option2_id,
    const char *option3_id
)
{
    switch (index) {
        case 0: return option0_id;
        case 1: return option1_id;
        case 2: return option2_id;
        case 3: return option3_id;
        default: return NULL;
    }
}

#if defined(DISPLAY_WASM_WITH_LVGL)
static const char *option_label_at(
    uint32_t index,
    const char *option0_label,
    const char *option1_label,
    const char *option2_label,
    const char *option3_label
)
{
    switch (index) {
        case 0: return option0_label;
        case 1: return option1_label;
        case 2: return option2_label;
        case 3: return option3_label;
        default: return NULL;
    }
}
#endif

static bool build_rules_snapshot(
    uint32_t sequence,
    const char *state,
    const char *action_id,
    int can_choose,
    int can_dismiss,
    uint32_t option_count,
    const char *option0_id,
    const char *option1_id,
    const char *option2_id,
    const char *option3_id,
    display_rules_snapshot_t *snapshot
)
{
    if (snapshot == NULL || state == NULL || action_id == NULL ||
        (can_choose != 0 && can_choose != 1) ||
        (can_dismiss != 0 && can_dismiss != 1) ||
        option_count > DISPLAY_RULES_OPTION_COUNT_MAX) {
        return false;
    }

    memset(snapshot, 0, sizeof(*snapshot));
    snapshot->schema = 1;
    snapshot->sequence = sequence;
    snapshot->state = state_from_name(state);
    if (snapshot->state == DISPLAY_RULES_UNKNOWN) return false;

    if (snapshot->state != DISPLAY_RULES_PROMPT) {
        return option_count == 0 && can_choose == 0 && can_dismiss == 0;
    }
    if (option_count == 0 || !copy_strict(
            snapshot->prompt.action_id,
            sizeof(snapshot->prompt.action_id),
            action_id)) {
        return false;
    }

    snapshot->prompt.present = true;
    snapshot->prompt.can_choose = can_choose != 0;
    snapshot->prompt.can_dismiss = can_dismiss != 0;
    snapshot->prompt.option_count = (uint8_t)option_count;
    for (uint32_t index = 0; index < option_count; index++) {
        const char *option_id = option_id_at(
            index,
            option0_id,
            option1_id,
            option2_id,
            option3_id);
        if (!copy_strict(
                snapshot->prompt.options[index].id,
                sizeof(snapshot->prompt.options[index].id),
                option_id)) {
            return false;
        }
    }
    return true;
}

#if defined(DISPLAY_WASM_WITH_LVGL)
static bool build_ui_snapshot(
    uint32_t sequence,
    const char *state,
    const char *response_text,
    const char *status_text,
    const char *account,
    const char *prompt_kind,
    const char *prompt_title,
    const char *prompt_body,
    const char *action_id,
    int timeout_seconds,
    int can_choose,
    int can_dismiss,
    uint32_t option_count,
    const char *option0_id,
    const char *option0_label,
    const char *option1_id,
    const char *option1_label,
    const char *option2_id,
    const char *option2_label,
    const char *option3_id,
    const char *option3_label,
    ui_snapshot_t *snapshot
)
{
    if (snapshot == NULL || response_text == NULL || status_text == NULL ||
        account == NULL || prompt_kind == NULL || prompt_title == NULL ||
        prompt_body == NULL || timeout_seconds < -1 || timeout_seconds == 0) {
        return false;
    }
    if (!ui_snapshot_init(snapshot) ||
        !ui_snapshot_set_state(snapshot, state) ||
        !ui_snapshot_set_text(snapshot, response_text, status_text[0] ? status_text : NULL) ||
        !copy_strict(snapshot->account, sizeof(snapshot->account), account)) {
        return false;
    }
    snapshot->sequence = sequence;
    if (snapshot->state != UI_DISPLAY_PROMPT) return true;

    if (!copy_strict(snapshot->prompt.kind, sizeof(snapshot->prompt.kind), prompt_kind) ||
        !copy_strict(snapshot->prompt.title, sizeof(snapshot->prompt.title), prompt_title) ||
        !copy_strict(snapshot->prompt.body, sizeof(snapshot->prompt.body), prompt_body) ||
        !copy_strict(snapshot->prompt.action_id, sizeof(snapshot->prompt.action_id), action_id)) {
        return false;
    }
    snapshot->prompt.can_choose = can_choose != 0;
    snapshot->prompt.can_dismiss = can_dismiss != 0;
    snapshot->prompt.timeout_seconds = timeout_seconds;
    snapshot->prompt.option_count = (uint8_t)option_count;
    for (uint32_t index = 0; index < option_count; index++) {
        const char *option_id = option_id_at(
            index,
            option0_id,
            option1_id,
            option2_id,
            option3_id);
        const char *option_label = option_label_at(
            index,
            option0_label,
            option1_label,
            option2_label,
            option3_label);
        if (!copy_strict(
                snapshot->prompt.options[index].id,
                sizeof(snapshot->prompt.options[index].id),
                option_id) ||
            !copy_strict(
                snapshot->prompt.options[index].label,
                sizeof(snapshot->prompt.options[index].label),
                option_label)) {
            return false;
        }
    }
    snapshot->prompt.present = true;
    return true;
}
#endif

int display_wasm_abi_version(void)
{
    return DISPLAY_WASM_ABI_VERSION;
}

int display_wasm_init(void)
{
    if (s_initialized) return DISPLAY_RULES_ACCEPTED;
#if defined(DISPLAY_WASM_WITH_LVGL)
    if (!init_lvgl()) return DISPLAY_RULES_INVALID_ARGUMENT;
#endif
    display_rules_init(&s_reducer);
    s_initialized = true;
    return DISPLAY_RULES_ACCEPTED;
}

int display_wasm_reset(void)
{
    if (!s_initialized) return display_wasm_init();
#if defined(DISPLAY_WASM_WITH_LVGL)
    s_pointer_x = 0;
    s_pointer_y = 0;
    s_pointer_pressed = false;
    clear_pending_action();
    return ui_display_set_connection_state(UI_DISPLAY_CONNECTION_CONNECTED);
#else
    display_rules_init(&s_reducer);
    return DISPLAY_RULES_ACCEPTED;
#endif
}

int display_wasm_state_from_name(const char *name)
{
    return state_from_name(name);
}

int display_wasm_apply_snapshot(
    uint32_t sequence,
    const char *state,
    const char *response_text,
    const char *status_text,
    const char *account,
    const char *prompt_kind,
    const char *prompt_title,
    const char *prompt_body,
    const char *action_id,
    int timeout_seconds,
    int can_choose,
    int can_dismiss,
    uint32_t option_count,
    const char *option0_id,
    const char *option0_label,
    const char *option1_id,
    const char *option1_label,
    const char *option2_id,
    const char *option2_label,
    const char *option3_id,
    const char *option3_label
)
{
    if (!s_initialized || response_text == NULL || status_text == NULL || account == NULL ||
        prompt_kind == NULL || prompt_title == NULL || prompt_body == NULL) {
        return DISPLAY_RULES_INVALID_ARGUMENT;
    }
    if (timeout_seconds < -1 || timeout_seconds == 0) {
        return DISPLAY_RULES_INVALID_SNAPSHOT;
    }

    display_rules_snapshot_t rules_snapshot;
    if (!build_rules_snapshot(
            sequence,
            state,
            action_id,
            can_choose,
            can_dismiss,
            option_count,
            option0_id,
            option1_id,
            option2_id,
            option3_id,
            &rules_snapshot)) {
        return DISPLAY_RULES_INVALID_SNAPSHOT;
    }

#if defined(DISPLAY_WASM_WITH_LVGL)
    ui_snapshot_t ui_snapshot;
    if (!build_ui_snapshot(
            sequence,
            state,
            response_text,
            status_text,
            account,
            prompt_kind,
            prompt_title,
            prompt_body,
            action_id,
            timeout_seconds,
            can_choose,
            can_dismiss,
            option_count,
            option0_id,
            option0_label,
            option1_id,
            option1_label,
            option2_id,
            option2_label,
            option3_id,
            option3_label,
            &ui_snapshot)) {
        return DISPLAY_RULES_INVALID_SNAPSHOT;
    }
    return ui_display_set_snapshot(&ui_snapshot);
#else
    (void)response_text;
    (void)status_text;
    (void)account;
    (void)prompt_kind;
    (void)prompt_title;
    (void)prompt_body;
    (void)timeout_seconds;
    (void)option0_label;
    (void)option1_label;
    (void)option2_label;
    (void)option3_label;
    return display_rules_apply_snapshot(&s_reducer, &rules_snapshot);
#endif
}

int display_wasm_validate_choice(const char *action_id, const char *choice)
{
    if (!s_initialized) return DISPLAY_RULES_INVALID_ARGUMENT;
#if defined(DISPLAY_WASM_WITH_LVGL)
    return ui_display_validate_choice(action_id, choice);
#else
    return display_rules_validate_choice(&s_reducer, action_id, choice);
#endif
}

int display_wasm_validate_dismiss(void)
{
    if (!s_initialized) return DISPLAY_RULES_INVALID_ARGUMENT;
#if defined(DISPLAY_WASM_WITH_LVGL)
    return ui_display_validate_dismiss();
#else
    return display_rules_validate_dismiss(&s_reducer);
#endif
}

int display_wasm_set_connection_state(int state)
{
    if (!s_initialized || state < 0 || state > 2) {
        return DISPLAY_RULES_INVALID_ARGUMENT;
    }
#if defined(DISPLAY_WASM_WITH_LVGL)
    clear_pending_action();
    return ui_display_set_connection_state((ui_display_connection_state_t)state);
#else
    if (state == 0) {
        display_rules_init(&s_reducer);
        return DISPLAY_RULES_ACCEPTED;
    }

    const display_rules_view_t *view = display_rules_view(&s_reducer);
    display_rules_snapshot_t snapshot = {
        .schema = 1,
        .sequence = view != NULL && view->initialized ? view->sequence + 1 : 0,
        .state = state == 1 ? DISPLAY_RULES_DISCONNECTED : DISPLAY_RULES_ERROR,
    };
    return display_rules_apply_snapshot(&s_reducer, &snapshot);
#endif
}

int display_wasm_set_pointer(int x, int y, int pressed)
{
#if defined(DISPLAY_WASM_WITH_LVGL)
    if (!s_initialized || x < 0 || x >= DISPLAY_WASM_WIDTH ||
        y < 0 || y >= DISPLAY_WASM_HEIGHT || (pressed != 0 && pressed != 1)) {
        return DISPLAY_RULES_INVALID_ARGUMENT;
    }
    s_pointer_x = (int16_t)x;
    s_pointer_y = (int16_t)y;
    s_pointer_pressed = pressed != 0;
    if (s_input_read_timer != NULL) {
        lv_timer_ready(s_input_read_timer);
        lv_timer_handler();
    }
    return DISPLAY_RULES_ACCEPTED;
#else
    (void)x;
    (void)y;
    (void)pressed;
    return DISPLAY_RULES_INVALID_ARGUMENT;
#endif
}

bool display_wasm_action_pending(void)
{
#if defined(DISPLAY_WASM_WITH_LVGL)
    return s_initialized && s_action_pending;
#else
    return false;
#endif
}

const char *display_wasm_action_id(void)
{
#if defined(DISPLAY_WASM_WITH_LVGL)
    return s_action_pending ? s_action_id : "";
#else
    return "";
#endif
}

const char *display_wasm_action_choice(void)
{
#if defined(DISPLAY_WASM_WITH_LVGL)
    return s_action_pending ? s_action_choice : "";
#else
    return "";
#endif
}

int display_wasm_action_clear(void)
{
#if defined(DISPLAY_WASM_WITH_LVGL)
    if (!s_initialized) return DISPLAY_RULES_INVALID_ARGUMENT;
    clear_pending_action();
#endif
    return DISPLAY_RULES_ACCEPTED;
}

static const display_rules_view_t *current_view(void)
{
#if defined(DISPLAY_WASM_WITH_LVGL)
    return ui_display_rules_view();
#else
    return display_rules_view(&s_reducer);
#endif
}

int display_wasm_view_state(void)
{
    const display_rules_view_t *view = current_view();
    return view != NULL && view->initialized ? view->state : DISPLAY_RULES_UNKNOWN;
}

uint32_t display_wasm_view_sequence(void)
{
    const display_rules_view_t *view = current_view();
    return view != NULL && view->initialized ? view->sequence : 0;
}

bool display_wasm_view_is_busy(void)
{
    const display_rules_view_t *view = current_view();
    return view != NULL && view->initialized && view->is_busy;
}

bool display_wasm_view_connection_healthy(void)
{
    const display_rules_view_t *view = current_view();
    return view != NULL && view->initialized && view->connection_healthy;
}

bool display_wasm_view_can_choose(void)
{
    const display_rules_view_t *view = current_view();
    return view != NULL && view->initialized && view->can_choose;
}

bool display_wasm_view_can_dismiss(void)
{
    const display_rules_view_t *view = current_view();
    return view != NULL && view->initialized && view->can_dismiss;
}

const uint32_t *display_wasm_framebuffer(void)
{
#if defined(DISPLAY_WASM_WITH_LVGL)
    return s_framebuffer;
#else
    return NULL;
#endif
}

uint32_t display_wasm_framebuffer_width(void)
{
    return DISPLAY_WASM_WIDTH;
}

uint32_t display_wasm_framebuffer_height(void)
{
    return DISPLAY_WASM_HEIGHT;
}

int display_wasm_tick(uint32_t elapsed_ms)
{
#if defined(DISPLAY_WASM_WITH_LVGL)
    if (!s_initialized) return DISPLAY_RULES_INVALID_ARGUMENT;
    lv_tick_inc(elapsed_ms);
    lv_timer_handler();
    return DISPLAY_RULES_ACCEPTED;
#else
    (void)elapsed_ms;
    return DISPLAY_RULES_INVALID_ARGUMENT;
#endif
}
