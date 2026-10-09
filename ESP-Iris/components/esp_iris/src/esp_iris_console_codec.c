#include "esp_iris_console_codec.h"

#include <string.h>

static const char s_base64[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

static int base64_value(uint8_t value)
{
    if (value >= 'A' && value <= 'Z') return value - 'A';
    if (value >= 'a' && value <= 'z') return value - 'a' + 26;
    if (value >= '0' && value <= '9') return value - '0' + 52;
    if (value == '+') return 62;
    if (value == '/') return 63;
    return -1;
}

esp_err_t iris_console_frame_encode(uint8_t *out, size_t capacity,
                                    const esp_iris_wire_header_t *header,
                                    const uint8_t *payload, size_t payload_size,
                                    bool request, size_t *out_size)
{
    const char *prefix = request ? IRIS_CONSOLE_REQUEST_PREFIX
                                : IRIS_CONSOLE_RESPONSE_PREFIX;
    const size_t prefix_size = strlen(prefix);
    if (out == NULL || out_size == NULL) return ESP_ERR_INVALID_ARG;
    if (capacity <= prefix_size + 2U) return ESP_ERR_INVALID_SIZE;
    size_t binary_size = 0;
    esp_err_t err = iris_frame_encode(out + prefix_size,
        capacity - prefix_size - 2U, header, payload, payload_size, &binary_size);
    if (err != ESP_OK) return err;
    const size_t groups = (binary_size + 2U) / 3U;
    const size_t size = prefix_size + groups * 4U + 2U;
    if (size > capacity) return ESP_ERR_INVALID_SIZE;

    /* Expand backwards in the caller's buffer. No full-frame temporary or
     * heap allocation is needed, including for the maximum RPC response. */
    for (size_t group = groups; group > 0; --group) {
        const size_t offset = (group - 1U) * 3U;
        const size_t remaining = binary_size - offset;
        const uint8_t *input = out + prefix_size + offset;
        const uint32_t value = (uint32_t)input[0] << 16 |
            (remaining > 1U ? (uint32_t)input[1] << 8 : 0) |
            (remaining > 2U ? input[2] : 0);
        uint8_t *output = out + prefix_size + (group - 1U) * 4U;
        output[0] = s_base64[(value >> 18) & 63U];
        output[1] = s_base64[(value >> 12) & 63U];
        output[2] = remaining > 1U ? s_base64[(value >> 6) & 63U] : '=';
        output[3] = remaining > 2U ? s_base64[value & 63U] : '=';
    }
    memcpy(out, prefix, prefix_size);
    out[size - 2U] = '\r';
    out[size - 1U] = '\n';
    *out_size = size;
    return ESP_OK;
}

esp_err_t iris_console_frame_decode(uint8_t *line, size_t length, bool request,
                                    iris_decoded_frame_t *frame)
{
    const char *prefix = request ? IRIS_CONSOLE_REQUEST_PREFIX
                                : IRIS_CONSOLE_RESPONSE_PREFIX;
    const size_t prefix_size = strlen(prefix);
    if (line == NULL || frame == NULL) return ESP_ERR_INVALID_ARG;
    if (length > IRIS_CONSOLE_RECORD_BYTES) return ESP_ERR_INVALID_SIZE;
    if (length > 0 && line[length - 1U] == '\n') --length;
    if (length > 0 && line[length - 1U] == '\r') --length;
    if (length <= prefix_size || memcmp(line, prefix, prefix_size) != 0 ||
            (length - prefix_size) % 4U != 0) return ESP_ERR_INVALID_RESPONSE;
    size_t decoded = 0;
    for (size_t offset = prefix_size; offset < length; offset += 4U) {
        const uint8_t *input = line + offset;
        const int a = base64_value(input[0]);
        const int b = base64_value(input[1]);
        const bool pad_c = input[2] == '=';
        const bool pad_d = input[3] == '=';
        const int c = pad_c ? 0 : base64_value(input[2]);
        const int d = pad_d ? 0 : base64_value(input[3]);
        if (a < 0 || b < 0 || c < 0 || d < 0 ||
                (pad_c && !pad_d) ||
                ((pad_c || pad_d) && offset + 4U != length) ||
                (pad_c && (b & 15) != 0) || (pad_d && (c & 3) != 0)) {
            return ESP_ERR_INVALID_RESPONSE;
        }
        const size_t count = pad_c ? 1U : pad_d ? 2U : 3U;
        if (decoded + count > ESP_IRIS_MAX_WIRE_FRAME_SIZE)
            return ESP_ERR_INVALID_SIZE;
        const uint32_t value = (uint32_t)a << 18 | (uint32_t)b << 12 |
            (uint32_t)c << 6 | (uint32_t)d;
        line[decoded++] = (uint8_t)(value >> 16);
        if (!pad_c) line[decoded++] = (uint8_t)(value >> 8);
        if (!pad_d) line[decoded++] = (uint8_t)value;
    }
    if (decoded < 2U || line[decoded - 1U] != 0)
        return ESP_ERR_INVALID_RESPONSE;
    return iris_frame_decode_in_place(line, decoded - 1U, frame);
}
