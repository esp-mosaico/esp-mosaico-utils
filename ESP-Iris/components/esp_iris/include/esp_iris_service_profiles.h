// SPDX-License-Identifier: Apache-2.0
#pragma once

/* Optional v1 RPC service profiles, reserved by protocol/spec.md.
 * Products register handlers explicitly. Generic RPC support alone does not
 * imply that a profile is implemented. Unknown methods must be rejected.
 * Pointer pixels use the current full-screen MEDIA OPEN description, never
 * a board-specific fixed resolution. Wire payload: <BBhhHI>, 12 bytes. */
#define ESP_IRIS_POINTER_SERVICE_ID 0x1001U
#define ESP_IRIS_POINTER_METHOD_ID 1U
#define ESP_IRIS_POINTER_MESSAGE_SIZE 12U
#define ESP_IRIS_RECOVERY_SERVICE_ID 0x7FFFU
#define ESP_IRIS_ENTER_RECOVERY_METHOD_ID 2U
