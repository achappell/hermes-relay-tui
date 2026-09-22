#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define TC_PAYLOAD_MAX 1024u
#define TC_WIRE_MAX 1050u
#define TC_BYTES_MAX 480000u
#define TC_DURATION_MS 15000u
#define TC_LEASE_MS 1000u
typedef enum {
  TC_HELLO = 1,
  TC_READY,
  TC_START,
  TC_STARTED,
  TC_PCM,
  TC_END,
  TC_ENDED,
  TC_ABORT,
  TC_KEEPALIVE,
  TC_ERROR
} tc_type_t;
typedef enum {
  TC_CANCELLED = 1,
  TC_TIMEOUT,
  TC_MALFORMED,
  TC_OVERFLOW,
  TC_I2S_FAILURE,
  TC_TRANSPORT_LOST,
  TC_BUSY
} tc_reason_t;
typedef struct {
  uint8_t type;
  uint16_t length;
  uint32_t generation, capture, sequence;
  uint8_t payload[TC_PAYLOAD_MAX];
} tc_frame_t;
typedef struct {
  uint8_t wire[TC_WIRE_MAX];
  size_t used;
  bool dropping;
} tc_parser_t;
uint32_t tc_crc32(const uint8_t *data, size_t size);
size_t tc_encode(const tc_frame_t *frame, uint8_t *wire, size_t capacity);
bool tc_decode(const uint8_t *wire, size_t size, tc_frame_t *frame);
/* 1 frame, 0 incomplete, -1 malformed (resynchronizes on delimiter). */
int tc_feed(tc_parser_t *parser, uint8_t byte, tc_frame_t *frame);
uint32_t tc_u32(const uint8_t *bytes);
void tc_put_u32(uint8_t *bytes, uint32_t value);
/* Philips left-slot signed 24-bit sample occupies bits 31..8. */
void tc_pcm16(uint32_t left_slot, uint8_t output[2]);
