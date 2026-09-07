#include "ui_snapshot.h"

#include <string.h>

static bool copy_bounded(char *destination, size_t capacity, const char *source)
{
    if (destination == NULL || capacity == 0 || source == NULL) {
        return false;
    }

    size_t length = strlen(source);
    if (length >= capacity) {
        length = capacity - 1;
    }
    memcpy(destination, source, length);
    destination[length] = '\0';
    return true;
}

ui_display_state_t ui_display_state_from_name(const char *name)
{
    if (name == NULL) return UI_DISPLAY_UNKNOWN;
    if (strcmp(name, "idle") == 0) return UI_DISPLAY_IDLE;
    if (strcmp(name, "heard") == 0) return UI_DISPLAY_HEARD;
    if (strcmp(name, "listening") == 0) return UI_DISPLAY_LISTENING;
    if (strcmp(name, "thinking") == 0) return UI_DISPLAY_THINKING;
    if (strcmp(name, "speaking") == 0) return UI_DISPLAY_SPEAKING;
    if (strcmp(name, "buffering") == 0) return UI_DISPLAY_BUFFERING;
    if (strcmp(name, "error") == 0) return UI_DISPLAY_ERROR;
    if (strcmp(name, "disconnected") == 0) return UI_DISPLAY_DISCONNECTED;
    if (strcmp(name, "prompt") == 0) return UI_DISPLAY_PROMPT;
    return UI_DISPLAY_UNKNOWN;
}

const char *ui_display_state_name(ui_display_state_t state)
{
    static const char *names[] = {
        "unknown", "idle", "heard", "listening", "thinking",
        "speaking", "buffering", "error", "disconnected", "prompt",
    };
    if (state < UI_DISPLAY_UNKNOWN || state > UI_DISPLAY_PROMPT) {
        return names[UI_DISPLAY_UNKNOWN];
    }
    return names[state];
}

bool ui_snapshot_init(ui_snapshot_t *snapshot)
{
    if (snapshot == NULL) return false;
    memset(snapshot, 0, sizeof(*snapshot));
    snapshot->schema = 1;
    snapshot->state = UI_DISPLAY_IDLE;
    return true;
}

bool ui_snapshot_set_state(ui_snapshot_t *snapshot, const char *name)
{
    if (snapshot == NULL) return false;
    ui_display_state_t state = ui_display_state_from_name(name);
    if (state == UI_DISPLAY_UNKNOWN) return false;
    snapshot->state = state;
    snapshot->prompt.present = state == UI_DISPLAY_PROMPT;
    return true;
}

bool ui_snapshot_set_text(ui_snapshot_t *snapshot, const char *response_text, const char *status_text)
{
    if (snapshot == NULL || response_text == NULL) return false;
    copy_bounded(snapshot->response_text, sizeof(snapshot->response_text), response_text);
    if (status_text == NULL) {
        snapshot->status_text[0] = '\0';
    } else {
        copy_bounded(snapshot->status_text, sizeof(snapshot->status_text), status_text);
    }
    return true;
}

bool ui_snapshot_to_rules(const ui_snapshot_t *snapshot, display_rules_snapshot_t *rules_snapshot)
{
    if (snapshot == NULL || rules_snapshot == NULL) return false;

    memset(rules_snapshot, 0, sizeof(*rules_snapshot));
    rules_snapshot->schema = snapshot->schema;
    rules_snapshot->sequence = snapshot->sequence;
    rules_snapshot->state = snapshot->state;
    rules_snapshot->prompt.present = snapshot->prompt.present;
    rules_snapshot->prompt.can_choose = snapshot->prompt.can_choose;
    rules_snapshot->prompt.can_dismiss = snapshot->prompt.can_dismiss;

    if (!snapshot->prompt.present) return true;

    copy_bounded(
        rules_snapshot->prompt.action_id,
        sizeof(rules_snapshot->prompt.action_id),
        snapshot->prompt.action_id);
    rules_snapshot->prompt.option_count = snapshot->prompt.option_count;
    for (uint8_t index = 0; index < snapshot->prompt.option_count; index++) {
        copy_bounded(
            rules_snapshot->prompt.options[index].id,
            sizeof(rules_snapshot->prompt.options[index].id),
            snapshot->prompt.options[index].id);
    }
    return true;
}
