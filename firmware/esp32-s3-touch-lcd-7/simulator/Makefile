CC ?= clang
CFLAGS ?= -O2 -Wall -Wextra -std=c11
SDL_CFLAGS ?= $(shell /opt/homebrew/bin/sdl2-config --cflags 2>/dev/null || sdl2-config --cflags)
SDL_LDFLAGS ?= $(shell /opt/homebrew/bin/sdl2-config --libs 2>/dev/null || sdl2-config --libs)

LVGL_DIR ?= lvgl
LVGL_SRC := $(shell find $(LVGL_DIR)/src -name '*.c' 2>/dev/null)

INCLUDES = -Iinclude -I../main/include -I$(LVGL_DIR) $(SDL_CFLAGS)
DEFINES = -DLV_CONF_INCLUDE_SIMPLE -DSIMULATOR_BUILD=1

SRCS = sdl_main.c ../main/src/ui_test.c $(LVGL_SRC)
OBJS = $(SRCS:.c=.o)
TARGET = esp32_display_sim

all: $(LVGL_DIR) $(TARGET)

$(LVGL_DIR):
	@echo "Fetching LVGL 8.3.11 sources..."
	git clone --depth 1 --branch v8.3.11 https://github.com/lvgl/lvgl.git $(LVGL_DIR)

$(TARGET): $(LVGL_DIR)
	@echo "Compiling native SDL2 simulator..."
	$(CC) $(CFLAGS) $(DEFINES) $(INCLUDES) sdl_main.c ../main/src/ui_test.c $(shell find $(LVGL_DIR)/src -name '*.c') $(SDL_LDFLAGS) -o $(TARGET)
	@echo "Build complete: ./$(TARGET)"

clean:
	rm -f $(TARGET)

.PHONY: all clean
