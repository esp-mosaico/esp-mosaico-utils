// SPDX-License-Identifier: Apache-2.0
#pragma once

/* Optional application metadata, independent of Recovery's protocol/ABI.
 * Keep it in the first rodata segment, immediately after esp_app_desc. */
#define MOSAICO_APP_ID_MAGIC "mosaico-proj-v1"
#define MOSAICO_APP_ID_END "mosaico-id-end"
typedef struct {
    char magic[16];
    char project_id[33]; /* 128-bit lowercase hexadecimal project identity. */
    char end[15];
} mosaico_app_identity_t;
