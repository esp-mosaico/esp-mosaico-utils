// SPDX-License-Identifier: Apache-2.0
#include "iris_display_input.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "esp_heap_caps.h"
#include "esp_iris.h"
#include "esp_iris_service_profiles.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define COPY_ATTEMPTS 3

typedef struct {
    raylib_lite_video_backend_t video;
    raylib_lite_input_queue_t *input;
    uint16_t width;
    uint16_t height;
    uint16_t *capture;
    bool registered;
} iris_display_input_state_t;

static iris_display_input_state_t s_iris_io;

static esp_err_t to_esp(raylib_lite_result_t result)
{
    switch (result) {
    case RAYLIB_LITE_OK:
        return ESP_OK;
    case RAYLIB_LITE_INVALID_ARGUMENT:
        return ESP_ERR_INVALID_ARG;
    case RAYLIB_LITE_INVALID_STATE:
    case RAYLIB_LITE_NOT_READY:
        return ESP_ERR_INVALID_STATE;
    case RAYLIB_LITE_NO_MEMORY:
        return ESP_ERR_NO_MEM;
    case RAYLIB_LITE_NOT_SUPPORTED:
        return ESP_ERR_NOT_SUPPORTED;
    case RAYLIB_LITE_BUSY:
    case RAYLIB_LITE_TIMEOUT:
        return ESP_ERR_TIMEOUT;
    default:
        return ESP_FAIL;
    }
}

static esp_err_t copy_latest_frame(iris_display_input_state_t *state)
{
    const size_t pixels = (size_t)state->width * state->height;
    for (int attempt = 0; attempt < COPY_ATTEMPTS; ++attempt) {
        const raylib_lite_result_t result =
            state->video.copy_latest(state->video.context, state->capture, pixels);
        if (result == RAYLIB_LITE_OK) {
            return ESP_OK;
        }
        if (result != RAYLIB_LITE_BUSY && result != RAYLIB_LITE_TIMEOUT) {
            return to_esp(result);
        }
        vTaskDelay(pdMS_TO_TICKS(1));
    }
    return ESP_ERR_TIMEOUT;
}

static esp_err_t screen_begin(const esp_iris_media_desc_t *requested,
                              esp_iris_media_desc_t *actual,
                              uint32_t *total_size,
                              void *user_ctx)
{
    (void)requested;
    iris_display_input_state_t *state = user_ctx;
    if (!state || !actual || !total_size || state->capture) {
        return ESP_ERR_INVALID_STATE;
    }

    const size_t pixels = (size_t)state->width * state->height;
    const size_t bytes = pixels * sizeof(uint16_t);
    if (bytes > UINT32_MAX) {
        return ESP_ERR_INVALID_SIZE;
    }

    state->capture = heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!state->capture) {
        return ESP_ERR_NO_MEM;
    }

    const esp_err_t err = copy_latest_frame(state);
    if (err != ESP_OK) {
        heap_caps_free(state->capture);
        state->capture = NULL;
        return err;
    }

    *actual = (esp_iris_media_desc_t) {
        .x = 0,
        .y = 0,
        .width = state->width,
        .height = state->height,
        .stride = (uint32_t)state->width * sizeof(uint16_t),
        .format = ESP_IRIS_PIXEL_FORMAT_RGB565,
        .quality = 0,
    };
    *total_size = (uint32_t)bytes;
    return ESP_OK;
}

static esp_err_t screen_read(uint32_t offset,
                             uint8_t *out,
                             size_t capacity,
                             size_t *out_size,
                             void *user_ctx)
{
    iris_display_input_state_t *state = user_ctx;
    if (!state || !state->capture || !out || !out_size || capacity == 0) {
        return ESP_ERR_INVALID_ARG;
    }

    const size_t total =
        (size_t)state->width * state->height * sizeof(uint16_t);
    if (offset >= total) {
        return ESP_ERR_INVALID_ARG;
    }

    size_t size = total - offset;
    if (size > capacity) {
        size = capacity;
    }
    memcpy(out, (const uint8_t *)state->capture + offset, size);
    *out_size = size;
    return ESP_OK;
}

static void screen_end(void *user_ctx)
{
    iris_display_input_state_t *state = user_ctx;
    if (!state) {
        return;
    }
    heap_caps_free(state->capture);
    state->capture = NULL;
}

static int16_t read_le_i16(const uint8_t *value)
{
    return (int16_t)((uint16_t)value[0] | ((uint16_t)value[1] << 8));
}

static void write_le_i16(uint8_t *value, int16_t data)
{
    value[0] = (uint8_t)data;
    value[1] = (uint8_t)((uint16_t)data >> 8);
}

static esp_err_t pointer_rpc(const esp_iris_rpc_request_t *request,
                             uint8_t *response,
                             size_t response_capacity,
                             size_t *response_size,
                             void *user_ctx)
{
    iris_display_input_state_t *state = user_ctx;
    if (!state || !request ||
            request->payload_size != ESP_IRIS_POINTER_MESSAGE_SIZE ||
            !response || response_capacity < ESP_IRIS_POINTER_MESSAGE_SIZE ||
            !response_size || request->payload[0] > 2) {
        return ESP_ERR_INVALID_SIZE;
    }

    int32_t x = read_le_i16(request->payload + 2);
    int32_t y = read_le_i16(request->payload + 4);
    if (x < 0) {
        x = 0;
    } else if (x >= state->width) {
        x = state->width - 1;
    }
    if (y < 0) {
        y = 0;
    } else if (y >= state->height) {
        y = state->height - 1;
    }

    const raylib_lite_input_event_t event = {
        .type = RAYLIB_LITE_INPUT_POINTER,
        .x = x,
        .y = y,
        .pressed = request->payload[0] != 2,
        .timestamp_us = (uint64_t)esp_timer_get_time(),
    };
    const raylib_lite_result_t result =
        raylib_lite_input_push(state->input, &event);
    if (result != RAYLIB_LITE_OK) {
        return to_esp(result);
    }

    memcpy(response, request->payload, ESP_IRIS_POINTER_MESSAGE_SIZE);
    write_le_i16(response + 2, (int16_t)x);
    write_le_i16(response + 4, (int16_t)y);
    *response_size = ESP_IRIS_POINTER_MESSAGE_SIZE;
    return ESP_OK;
}

esp_err_t mosaico_iris_display_input_register(
    raylib_lite_video_backend_t video,
    raylib_lite_input_queue_t *input,
    uint16_t width,
    uint16_t height)
{
    if (s_iris_io.registered) {
        return ESP_ERR_INVALID_STATE;
    }
    if (!input || !width || !height || !video.copy_latest) {
        return ESP_ERR_INVALID_ARG;
    }

    memset(&s_iris_io, 0, sizeof(s_iris_io));
    s_iris_io.video = video;
    s_iris_io.input = input;
    s_iris_io.width = width;
    s_iris_io.height = height;

    const esp_iris_screen_backend_t screen = {
        .begin = screen_begin,
        .read = screen_read,
        .end = screen_end,
        .user_ctx = &s_iris_io,
    };
    esp_err_t err = esp_iris_screen_register(&screen);
    if (err != ESP_OK) {
        memset(&s_iris_io, 0, sizeof(s_iris_io));
        return err;
    }

    s_iris_io.registered = true;
    err = esp_iris_rpc_register(
        ESP_IRIS_POINTER_SERVICE_ID,
        ESP_IRIS_POINTER_METHOD_ID,
        pointer_rpc,
        &s_iris_io);
    if (err != ESP_OK) {
        esp_err_t cleanup = mosaico_iris_display_input_unregister();
        return cleanup == ESP_OK ? err : cleanup;
    }

    s_iris_io.registered = true;
    return ESP_OK;
}

esp_err_t mosaico_iris_display_input_unregister(void)
{
    if (!s_iris_io.registered) {
        heap_caps_free(s_iris_io.capture);
        memset(&s_iris_io, 0, sizeof(s_iris_io));
        return ESP_OK;
    }

    const esp_err_t rpc_err = esp_iris_rpc_unregister(
        ESP_IRIS_POINTER_SERVICE_ID, ESP_IRIS_POINTER_METHOD_ID);
    if (rpc_err != ESP_OK && rpc_err != ESP_ERR_NOT_FOUND) {
        return rpc_err;
    }

    const esp_err_t screen_err = esp_iris_screen_unregister(&s_iris_io);
    if (screen_err != ESP_OK && screen_err != ESP_ERR_NOT_FOUND) {
        return screen_err;
    }

    heap_caps_free(s_iris_io.capture);
    memset(&s_iris_io, 0, sizeof(s_iris_io));
    return ESP_OK;
}
