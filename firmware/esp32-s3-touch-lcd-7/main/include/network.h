#pragma once
#include "esp_err.h"
#include <stdbool.h>
esp_err_t network_start(void);
bool network_ready(void);

/* Called by the network worker, never by LVGL. */
void network_poll(void);
