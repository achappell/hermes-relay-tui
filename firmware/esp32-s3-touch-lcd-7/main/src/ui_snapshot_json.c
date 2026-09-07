#include "ui_snapshot.h"

#include "cJSON.h"

#include <string.h>

static bool copy_bounded(char *destination, size_t capacity, const char *source)
{
    if (destination == NULL || capacity == 0 || source == NULL) return false;
    size_t length = strlen(source);
    if (length >= capacity) length = capacity - 1;
    memcpy(destination, source, length);
    destination[length] = '\0';
    return true;
}

static const cJSON *object_item(const cJSON *object, const char *name)
{
    return cJSON_GetObjectItemCaseSensitive(object, name);
}

static bool required_string(const cJSON *object, const char *name, char *destination, size_t capacity)
{
    const cJSON *item = object_item(object, name);
    return cJSON_IsString(item) && item->valuestring[0] != '\0' &&
           copy_bounded(destination, capacity, item->valuestring);
}

static bool optional_string(const cJSON *object, const char *name, char *destination, size_t capacity)
{
    const cJSON *item = object_item(object, name);
    if (item == NULL || cJSON_IsNull(item)) {
        destination[0] = '\0';
        return true;
    }
    return cJSON_IsString(item) && copy_bounded(destination, capacity, item->valuestring);
}

static bool required_text(const cJSON *object, const char *name, char *destination, size_t capacity)
{
    const cJSON *item = object_item(object, name);
    return cJSON_IsString(item) && copy_bounded(destination, capacity, item->valuestring);
}

static bool parse_prompt(const cJSON *raw, ui_snapshot_prompt_t *prompt)
{
    if (!cJSON_IsObject(raw)) return false;
    const cJSON *options = object_item(raw, "options");
    if (!cJSON_IsArray(options) || cJSON_GetArraySize(options) < 1 ||
        cJSON_GetArraySize(options) > UI_SNAPSHOT_OPTION_COUNT_MAX) {
        return false;
    }
    if (!required_string(raw, "kind", prompt->kind, sizeof(prompt->kind)) ||
        !required_string(raw, "title", prompt->title, sizeof(prompt->title)) ||
        !required_text(raw, "body", prompt->body, sizeof(prompt->body)) ||
        !required_string(raw, "action_id", prompt->action_id, sizeof(prompt->action_id))) {
        return false;
    }
    prompt->timeout_seconds = -1;
    const cJSON *timeout = object_item(raw, "timeout_seconds");
    if (timeout != NULL && !cJSON_IsNull(timeout)) {
        if (!cJSON_IsNumber(timeout) || timeout->valuedouble <= 0 || timeout->valuedouble != timeout->valueint) {
            return false;
        }
        prompt->timeout_seconds = timeout->valueint;
    }
    prompt->option_count = (uint8_t)cJSON_GetArraySize(options);
    for (uint8_t index = 0; index < prompt->option_count; index++) {
        const cJSON *option = cJSON_GetArrayItem(options, index);
        if (!cJSON_IsObject(option) ||
            !required_string(option, "id", prompt->options[index].id, sizeof(prompt->options[index].id)) ||
            !required_string(option, "label", prompt->options[index].label, sizeof(prompt->options[index].label))) {
            return false;
        }
    }
    prompt->present = true;
    return true;
}

bool ui_snapshot_from_json(const char *json, ui_snapshot_t *snapshot)
{
    if (json == NULL || snapshot == NULL) return false;
    cJSON *root = cJSON_Parse(json);
    if (root == NULL) return false;

    bool valid = false;
    do {
        const cJSON *type = object_item(root, "type");
        const cJSON *schema = object_item(root, "schema");
        const cJSON *sequence = object_item(root, "sequence");
        const cJSON *state = object_item(root, "state");
        const cJSON *response = object_item(root, "response_text");
        const cJSON *status = object_item(root, "status_text");
        if (!cJSON_IsString(type) || strcmp(type->valuestring, "snapshot") != 0 ||
            !cJSON_IsNumber(schema) || schema->valuedouble != 1.0 ||
            !cJSON_IsNumber(sequence) || sequence->valuedouble < 0 ||
            sequence->valuedouble != sequence->valueint || sequence->valuedouble > UINT32_MAX ||
            !cJSON_IsString(state) || !cJSON_IsString(response) ||
            (status != NULL && !cJSON_IsNull(status) && !cJSON_IsString(status))) {
            break;
        }
        if (!ui_snapshot_init(snapshot) || !ui_snapshot_set_state(snapshot, state->valuestring)) break;
        snapshot->sequence = (uint32_t)sequence->valueint;
        if (!ui_snapshot_set_text(
                snapshot,
                response->valuestring,
                cJSON_IsString(status) ? status->valuestring : NULL)) {
            break;
        }
        if (!optional_string(root, "account", snapshot->account, sizeof(snapshot->account))) break;

        const cJSON *prompt = object_item(root, "prompt");
        if (snapshot->state == UI_DISPLAY_PROMPT) {
            if (!parse_prompt(prompt, &snapshot->prompt)) break;
        } else if (prompt != NULL && !cJSON_IsNull(prompt)) {
            break;
        }
        valid = true;
    } while (0);

    cJSON_Delete(root);
    return valid;
}
