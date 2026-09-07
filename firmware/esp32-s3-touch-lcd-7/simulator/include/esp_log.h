#pragma once
#include <stdio.h>

#define ESP_LOGI(tag, fmt, ...) printf("[INFO]  [%s] " fmt "\n", tag, ##__VA_ARGS__)
#define ESP_LOGW(tag, fmt, ...) printf("[WARN]  [%s] " fmt "\n", tag, ##__VA_ARGS__)
#define ESP_LOGE(tag, fmt, ...) printf("[ERROR] [%s] " fmt "\n", tag, ##__VA_ARGS__)
#define ESP_LOGD(tag, fmt, ...) printf("[DEBUG] [%s] " fmt "\n", tag, ##__VA_ARGS__)
