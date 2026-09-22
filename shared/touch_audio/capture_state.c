#include "capture_state.h"
#include <string.h>
void tc_abort(tc_state_t *s) {
  s->phase = s->generation ? TC_IDLE : TC_UNBOUND;
  s->ended = false;
  s->bytes = 0;
  s->sequence = 0;
}
void tc_ended(tc_state_t *s) {
  s->phase = TC_IDLE;
  s->ended = true;
}
int tc_command(tc_state_t *s, const tc_frame_t *f, uint64_t now) {
  if (f->type == TC_HELLO) {
    if (f->generation == s->generation)
      return s->phase == TC_IDLE ? 1 : 0;
    memset(s, 0, sizeof(*s));
    s->generation = f->generation;
    s->phase = TC_IDLE;
    return 1;
  }
  if (f->generation != s->generation || !s->generation)
    return 0;
  if (f->type == TC_START) {
    if (f->capture <= s->last_capture)
      return 0;
    if (s->phase != TC_IDLE)
      return -1;
    s->capture = f->capture;
    s->last_capture = f->capture;
    s->sequence = s->bytes = 0;
    s->ended = false;
    s->phase = TC_STARTING;
    s->lease = now;
    return 1;
  }
  if (f->capture != s->capture)
    return 0;
  if (f->type == TC_END && s->ended)
    return 2;
  /* S3 and C6 enforce the same automatic limit independently. An END may
   * therefore cross the C6 stop/drain boundary without invalidating PCM. */
  if (f->type == TC_END && s->phase == TC_DRAINING)
    return 0;
  if (s->phase == TC_IDLE || s->phase == TC_UNBOUND)
    return 0;
  if (f->type == TC_KEEPALIVE) {
    s->lease = now;
    return 1;
  }
  if (f->type == TC_ABORT) {
    tc_abort(s);
    return 1;
  }
  if (f->type == TC_END && s->phase == TC_CAPTURING) {
    s->phase = TC_DRAINING;
    return 1;
  }
  return -1;
}
bool tc_started(tc_state_t *s, uint64_t now) {
  if (s->phase != TC_STARTING || now - s->lease >= TC_LEASE_MS)
    return false;
  s->phase = TC_CAPTURING;
  s->started = now;
  return true;
}
bool tc_accept_pcm(tc_state_t *s, size_t n) {
  if ((s->phase != TC_CAPTURING && s->phase != TC_DRAINING) || !n || (n & 1) || n > TC_PAYLOAD_MAX ||
      n > TC_BYTES_MAX - s->bytes)
    return false;
  s->bytes += (uint32_t)n;
  s->sequence++;
  return true;
}
int tc_tick(tc_state_t *s, uint64_t now) {
  if (s->phase == TC_IDLE || s->phase == TC_UNBOUND)
    return 0;
  if (now - s->lease >= TC_LEASE_MS)
    return -1;
  if (s->phase == TC_CAPTURING &&
      (s->bytes == TC_BYTES_MAX || now - s->started >= TC_DURATION_MS)) {
    s->phase = TC_DRAINING;
    return 1;
  }
  return 0;
}
