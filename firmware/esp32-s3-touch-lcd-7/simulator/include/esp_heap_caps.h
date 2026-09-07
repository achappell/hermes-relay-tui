#pragma once
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>

#define MALLOC_CAP_SPIRAM   (1 << 0)
#define MALLOC_CAP_INTERNAL (1 << 1)
#define MALLOC_CAP_8BIT     (1 << 2)

static inline size_t heap_caps_get_free_size(uint32_t caps) {
    if (caps & MALLOC_CAP_SPIRAM) {
        return 5688 * 1024; // 5.68 MB free Octal PSRAM
    }
    return 384 * 1024;     // 384 KB free SRAM
}

static inline size_t heap_caps_get_total_size(uint32_t caps) {
    if (caps & MALLOC_CAP_SPIRAM) {
        return 8192 * 1024; // 8 MB total Octal PSRAM
    }
    return 512 * 1024;      // 512 KB total SRAM
}

static inline void *heap_caps_malloc(size_t size, uint32_t caps) {
    (void)caps;
    return malloc(size);
}

static inline void *heap_caps_realloc(void *ptr, size_t size, uint32_t caps) {
    (void)caps;
    return realloc(ptr, size);
}
