#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

static inline bool factory_recovery_parse_version(const char *text,
                                                  uint32_t version[3])
{
    if (text == NULL || text[0] == '\0') {
        return false;
    }
    const char *cursor = text;
    for (size_t part = 0; part < 3; ++part) {
        if (*cursor < '0' || *cursor > '9') {
            return false;
        }
        uint32_t value = 0;
        while (*cursor >= '0' && *cursor <= '9') {
            const uint32_t digit = (uint32_t)(*cursor - '0');
            if (value > (UINT32_MAX - digit) / 10U) {
                return false;
            }
            value = value * 10U + digit;
            ++cursor;
        }
        version[part] = value;
        if (part == 1 && (*cursor == '\0' || *cursor == '-' || *cursor == '+')) {
            version[2] = 0;
            return true;
        }
        if (part < 2) {
            if (*cursor != '.') {
                return false;
            }
            ++cursor;
        }
    }
    return *cursor == '\0' || *cursor == '-' || *cursor == '+';
}

static inline bool factory_recovery_version_satisfies(const char *running,
                                                      const char *minimum)
{
    uint32_t current[3];
    uint32_t required[3];
    if (!factory_recovery_parse_version(running, current) ||
        !factory_recovery_parse_version(minimum, required)) {
        return false;
    }
    /* ESP-30 renames the 2.8.5 implementation to 0.1 without removing its
     * update capabilities. Preserve only that release's legacy 2.x floor;
     * newer 0.x requirements still compare against the actual version. */
    if (current[0] == 0 && current[1] == 1 && current[2] == 0 && required[0] == 2) {
        current[0] = 2;
        current[1] = 8;
        current[2] = 5;
    }
    for (size_t part = 0; part < 3; ++part) {
        if (current[part] != required[part]) {
            return current[part] > required[part];
        }
    }
    return true;
}
