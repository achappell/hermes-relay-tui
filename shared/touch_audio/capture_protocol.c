#include "capture_protocol.h"
#include <string.h>
uint32_t tc_u32(const uint8_t *b) {
  return (uint32_t)b[0] | ((uint32_t)b[1] << 8) | ((uint32_t)b[2] << 16) |
         ((uint32_t)b[3] << 24);
}
void tc_put_u32(uint8_t *b, uint32_t v) {
  for (unsigned i = 0; i < 4; i++)
    b[i] = (uint8_t)(v >> (i * 8));
}
uint32_t tc_crc32(const uint8_t *b, size_t n) {
  uint32_t c = ~0u;
  while (n--) {
    c ^= *b++;
    for (int i = 0; i < 8; i++)
      c = (c >> 1) ^ ((0u - (c & 1u)) & 0xedb88320u);
  }
  return ~c;
}
static bool valid(const tc_frame_t *f) {
  if (!f->generation || f->type < TC_HELLO || f->type > TC_ERROR ||
      f->length > TC_PAYLOAD_MAX)
    return false;
  if (f->type == TC_HELLO || f->type == TC_READY)
    return !f->capture && !f->sequence && !f->length;
  if (!f->capture)
    return false;
  if (f->type == TC_PCM)
    return f->length && !(f->length & 1);
  if (f->type == TC_ENDED)
    return f->length == 4;
  if (f->sequence)
    return false;
  if (f->type == TC_ABORT || f->type == TC_ERROR)
    return f->length == 1 && f->payload[0] >= 1 && f->payload[0] <= 7;
  return !f->length;
}
size_t tc_encode(const tc_frame_t *f, uint8_t *out, size_t cap) {
  if (!valid(f) || cap < TC_WIRE_MAX)
    return 0;
  uint8_t raw[1044];
  raw[0] = 1;
  raw[1] = f->type;
  raw[2] = (uint8_t)f->length;
  raw[3] = (uint8_t)(f->length >> 8);
  tc_put_u32(raw + 4, f->generation);
  tc_put_u32(raw + 8, f->capture);
  tc_put_u32(raw + 12, f->sequence);
  memcpy(raw + 16, f->payload, f->length);
  tc_put_u32(raw + 16 + f->length, tc_crc32(raw, 16 + f->length));
  size_t w = 1, code_at = 0;
  uint8_t code = 1;
  for (size_t i = 0; i < 20u + f->length; i++) {
    if (!raw[i]) {
      out[code_at] = code;
      code = 1;
      code_at = w++;
    } else {
      out[w++] = raw[i];
      if (++code == 255) {
        out[code_at] = code;
        code = 1;
        code_at = w++;
      }
    }
  }
  out[code_at] = code;
  out[w++] = 0;
  return w;
}
bool tc_decode(const uint8_t *in, size_t n, tc_frame_t *f) {
  uint8_t raw[1044];
  size_t r = 0, w = 0;
  if (!n || n >= TC_WIRE_MAX)
    return false;
  while (r < n) {
    uint8_t c = in[r++];
    if (!c || r + (size_t)c - 1 > n)
      return false;
    for (unsigned i = 1; i < c; i++) {
      if (w >= sizeof(raw) || !in[r])
        return false;
      raw[w++] = in[r++];
    }
    if (c != 255 && r < n) {
      if (w >= sizeof(raw))
        return false;
      raw[w++] = 0;
    }
  }
  if (w < 20 || raw[0] != 1)
    return false;
  uint16_t len = (uint16_t)(raw[2] | ((uint16_t)raw[3] << 8));
  if (len > TC_PAYLOAD_MAX || w != 20u + len ||
      tc_u32(raw + 16 + len) != tc_crc32(raw, 16 + len))
    return false;
  f->type = raw[1];
  f->length = len;
  f->generation = tc_u32(raw + 4);
  f->capture = tc_u32(raw + 8);
  f->sequence = tc_u32(raw + 12);
  memcpy(f->payload, raw + 16, len);
  return valid(f);
}
int tc_feed(tc_parser_t *p, uint8_t b, tc_frame_t *f) {
  if (b) {
    if (p->dropping)
      return 0;
    if (p->used >= TC_WIRE_MAX - 1) {
      p->dropping = true;
      return -1;
    }
    p->wire[p->used++] = b;
    return 0;
  }
  bool bad = p->dropping;
  size_t n = p->used;
  p->used = 0;
  p->dropping = false;
  if (bad)
    return -1;
  if (!n)
    return 0;
  return tc_decode(p->wire, n, f) ? 1 : -1;
}
void tc_pcm16(uint32_t slot, uint8_t out[2]) {
  out[0] = (uint8_t)(slot >> 16);
  out[1] = (uint8_t)(slot >> 24);
}
