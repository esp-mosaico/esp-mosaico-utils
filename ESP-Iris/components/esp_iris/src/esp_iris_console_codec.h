#pragma once

#include "esp_iris_codec.h"

/* A console record is printable and bounded independently of object size.
 * Binary framing remains private to the dedicated data interface. */
#define IRIS_CONSOLE_REQUEST_PREFIX "iris @"
#define IRIS_CONSOLE_RESPONSE_PREFIX "@iris/0.2 "
#define IRIS_CONSOLE_RECORD_BYTES \
    (sizeof(IRIS_CONSOLE_RESPONSE_PREFIX) - 1U + \
     4U * ((ESP_IRIS_MAX_WIRE_FRAME_SIZE + 2U) / 3U) + 2U)

esp_err_t iris_console_frame_encode(uint8_t *out, size_t capacity,
                                    const esp_iris_wire_header_t *header,
                                    const uint8_t *payload, size_t payload_size,
                                    bool request, size_t *out_size);

/* Decode one complete line (with or without CR/LF) in place. The caller owns
 * the line buffer and the returned payload lives in that same buffer. */
esp_err_t iris_console_frame_decode(uint8_t *line, size_t length, bool request,
                                    iris_decoded_frame_t *frame);
