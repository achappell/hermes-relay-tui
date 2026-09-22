#pragma once
#include "capture_protocol.h"
typedef enum {
  TC_UNBOUND,
  TC_IDLE,
  TC_STARTING,
  TC_CAPTURING,
  TC_DRAINING
} tc_phase_t;
typedef struct {
  tc_phase_t phase;
  uint32_t generation, capture, last_capture, sequence, bytes;
  uint64_t lease, started;
  bool ended;
} tc_state_t;
/* C6 command reducer: 1 accepted, 2 cached END, 0 stale/ignored, -1 invalid. */
int tc_command(tc_state_t *s, const tc_frame_t *f, uint64_t now);
bool tc_started(tc_state_t *s, uint64_t now);
bool tc_accept_pcm(tc_state_t *s, size_t bytes);
/* 1 normal automatic finish, -1 expired lease, 0 continue. */
int tc_tick(tc_state_t *s, uint64_t now);
void tc_abort(tc_state_t *s);
void tc_ended(tc_state_t *s);
