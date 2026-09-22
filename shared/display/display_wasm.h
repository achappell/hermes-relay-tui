#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "display_rules.h"

#define DISPLAY_WASM_ABI_VERSION 3

int display_wasm_abi_version(void);
int display_wasm_init(void);
int display_wasm_reset(void);

int display_wasm_state_from_name(const char *name);

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
);

int display_wasm_begin_typed_choice_snapshot(
    uint32_t sequence,
    const char *response_text,
    const char *status_text,
    const char *account,
    const char *action_id,
    const char *title,
    const char *body,
    const char *object_id,
    const char *freshness,
    int can_choose,
    int can_explore,
    int allows_choose,
    int allows_explore,
    uint32_t option_count
);
int display_wasm_set_typed_choice_option(
    uint32_t index,
    const char *option_id,
    const char *label
);
int display_wasm_finish_typed_choice_snapshot(void);

int display_wasm_validate_choice(const char *action_id, const char *choice);
int display_wasm_validate_typed_choice(
    const char *action_id,
    const char *operation,
    const char *option_id,
    const char *object_id,
    const char *freshness
);
int display_wasm_validate_dismiss(void);
int display_wasm_set_connection_state(int state);

int display_wasm_set_pointer(int x, int y, int pressed);
bool display_wasm_action_pending(void);
const char *display_wasm_action_id(void);
const char *display_wasm_action_choice(void);
const char *display_wasm_action_operation(void);
const char *display_wasm_action_object_id(void);
const char *display_wasm_action_freshness(void);
int display_wasm_action_clear(void);

int display_wasm_view_state(void);
uint32_t display_wasm_view_sequence(void);
bool display_wasm_view_is_busy(void);
bool display_wasm_view_connection_healthy(void);
bool display_wasm_view_can_choose(void);
bool display_wasm_view_can_explore(void);
bool display_wasm_view_can_dismiss(void);

#define DISPLAY_WASM_WIDTH 1024
#define DISPLAY_WASM_HEIGHT 600

const uint32_t *display_wasm_framebuffer(void);
uint32_t display_wasm_framebuffer_width(void);
uint32_t display_wasm_framebuffer_height(void);
int display_wasm_tick(uint32_t elapsed_ms);
