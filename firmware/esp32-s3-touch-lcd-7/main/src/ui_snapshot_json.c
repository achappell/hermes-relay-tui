#include "ui_snapshot.h"

#include "cJSON.h"

#include <string.h>

static bool copy_strict(char *destination, size_t capacity, const char *source)
{
    if (destination == NULL || capacity == 0 || source == NULL) return false;
    size_t length = strlen(source);
    if (length >= capacity) return false;
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
           copy_strict(destination, capacity, item->valuestring);
}

static bool optional_string(const cJSON *object, const char *name, char *destination, size_t capacity)
{
    const cJSON *item = object_item(object, name);
    if (item == NULL || cJSON_IsNull(item)) {
        destination[0] = '\0';
        return true;
    }
    return cJSON_IsString(item) && copy_strict(destination, capacity, item->valuestring);
}

static bool required_text(const cJSON *object, const char *name, char *destination, size_t capacity)
{
    const cJSON *item = object_item(object, name);
    return cJSON_IsString(item) && copy_strict(destination, capacity, item->valuestring);
}

/* Back a byte cutoff up to the end of the last complete UTF-8 sequence at or
   before it, so a multi-byte codepoint straddling the cutoff is dropped
   whole rather than split into an invalid trailing byte sequence. */
static size_t utf8_safe_cut(const char *text, size_t length)
{
    if (length == 0) return 0;

    size_t lead = length;
    int steps_back = 0;
    while (lead > 0 && steps_back < 3 &&
           (((unsigned char)text[lead - 1]) & 0xC0) == 0x80) {
        lead--;
        steps_back++;
    }
    if (lead == 0) return 0;

    unsigned char lead_byte = (unsigned char)text[lead - 1];
    size_t sequence_length;
    if (lead_byte < 0x80) {
        sequence_length = 1;
    } else if ((lead_byte & 0xE0) == 0xC0) {
        sequence_length = 2;
    } else if ((lead_byte & 0xF0) == 0xE0) {
        sequence_length = 3;
    } else if ((lead_byte & 0xF8) == 0xF0) {
        sequence_length = 4;
    } else {
        /* Not a valid UTF-8 leading byte either; drop it too. */
        return lead - 1;
    }

    if (lead - 1 + sequence_length > length) {
        /* This codepoint is cut off by the boundary: drop it whole. */
        return lead - 1;
    }
    return length;
}

/* The host bounds a final transcript at 4000 characters, far more than the
   panel's confirmation line holds. Truncate rather than rejecting an
   otherwise valid snapshot: the answer and the connection state matter more
   than the last few words of what the room said. */
static bool optional_truncated_text(
    const cJSON *object, const char *name, char *destination, size_t capacity)
{
    const cJSON *item = object_item(object, name);
    if (item == NULL || cJSON_IsNull(item)) {
        destination[0] = '\0';
        return true;
    }
    if (!cJSON_IsString(item) || capacity == 0) return false;
    size_t length = strlen(item->valuestring);
    if (length >= capacity) {
        length = utf8_safe_cut(item->valuestring, capacity - 1);
    }
    memcpy(destination, item->valuestring, length);
    destination[length] = '\0';
    return true;
}

static bool parse_capabilities(const cJSON *root, ui_snapshot_t *snapshot)
{
    const cJSON *raw = object_item(root, "capabilities");
    snapshot->prompt.can_choose = false;
    snapshot->prompt.can_explore = false;
    snapshot->prompt.can_dismiss = false;
    if (raw == NULL) return true;
    if (!cJSON_IsObject(raw)) return false;

    const cJSON *actions = object_item(raw, "actions");
    const cJSON *features = object_item(raw, "features");
    if (!cJSON_IsArray(actions) || !cJSON_IsArray(features)) return false;

    cJSON *action = NULL;
    cJSON_ArrayForEach(action, actions) {
        if (!cJSON_IsString(action)) return false;
        if (strcmp(action->valuestring, "prompt.choose") == 0) {
            if (snapshot->prompt.can_choose) return false;
            snapshot->prompt.can_choose = true;
        } else if (strcmp(action->valuestring, "prompt.explore") == 0) {
            if (snapshot->prompt.can_explore) return false;
            snapshot->prompt.can_explore = true;
        } else if (strcmp(action->valuestring, "prompt.dismiss") == 0) {
            if (snapshot->prompt.can_dismiss) return false;
            snapshot->prompt.can_dismiss = true;
        } else {
            return false;
        }
    }

    cJSON *feature = NULL;
    cJSON_ArrayForEach(feature, features) {
        if (!cJSON_IsString(feature) || feature->valuestring[0] == '\0') return false;
    }
    return true;
}

static bool parse_prompt(const cJSON *raw, ui_snapshot_prompt_t *prompt)
{
    if (!cJSON_IsObject(raw)) return false;
    const cJSON *choice = object_item(raw, "choice");
    prompt->typed_choice = choice != NULL;
    if (prompt->typed_choice && !cJSON_IsObject(choice)) return false;
    if (!required_string(raw, "kind", prompt->kind, sizeof(prompt->kind)) ||
        !required_string(raw, "title", prompt->title, sizeof(prompt->title)) ||
        !required_text(raw, "body", prompt->body, sizeof(prompt->body)) ||
        !required_string(raw, "action_id", prompt->action_id, sizeof(prompt->action_id))) {
        return false;
    }
    if (prompt->typed_choice && strcmp(prompt->kind, "choice") != 0) return false;
    size_t body_length = strlen(prompt->body);
    if (body_length > (prompt->typed_choice ? 1024 : 192)) return false;

    const cJSON *options = object_item(raw, "options");
    if (!cJSON_IsArray(options) || cJSON_GetArraySize(options) < 1 ||
        cJSON_GetArraySize(options) > (prompt->typed_choice
            ? UI_SNAPSHOT_OPTION_COUNT_MAX
            : UI_SNAPSHOT_GENERIC_OPTION_COUNT_MAX)) {
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
        size_t id_length = strlen(prompt->options[index].id);
        size_t label_length = strlen(prompt->options[index].label);
        if (id_length > (prompt->typed_choice ? 64 : 32) ||
            label_length > (prompt->typed_choice ? 256 : 48)) {
            return false;
        }
        for (uint8_t previous = 0; previous < index; previous++) {
            if (strcmp(prompt->options[index].id, prompt->options[previous].id) == 0) {
                return false;
            }
        }
    }
    if (prompt->typed_choice) {
        if (!required_string(choice, "object_id", prompt->object_id, sizeof(prompt->object_id)) ||
            !required_string(choice, "freshness", prompt->freshness, sizeof(prompt->freshness))) {
            return false;
        }
        const cJSON *operations = object_item(choice, "operations");
        if (!cJSON_IsArray(operations) || cJSON_GetArraySize(operations) < 1 ||
            cJSON_GetArraySize(operations) > 2) {
            return false;
        }
        cJSON *operation = NULL;
        cJSON_ArrayForEach(operation, operations) {
            if (!cJSON_IsString(operation)) return false;
            if (strcmp(operation->valuestring, "choose") == 0) {
                if (prompt->allows_choose) return false;
                prompt->allows_choose = true;
            } else if (strcmp(operation->valuestring, "explore") == 0) {
                if (prompt->allows_explore) return false;
                prompt->allows_explore = true;
            } else {
                return false;
            }
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
        if (!optional_truncated_text(
                root,
                "transcript_text",
                snapshot->transcript_text,
                sizeof(snapshot->transcript_text))) {
            break;
        }
        if (!optional_string(root, "account", snapshot->account, sizeof(snapshot->account))) break;

        const cJSON *prompt = object_item(root, "prompt");
        if (snapshot->state == UI_DISPLAY_PROMPT) {
            if (!parse_prompt(prompt, &snapshot->prompt)) break;
        } else if (prompt != NULL && !cJSON_IsNull(prompt)) {
            break;
        }
        if (!parse_capabilities(root, snapshot)) break;
        valid = true;
    } while (0);

    cJSON_Delete(root);
    return valid;
}
