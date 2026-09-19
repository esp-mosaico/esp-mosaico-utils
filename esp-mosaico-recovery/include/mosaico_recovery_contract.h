// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <stddef.h>
#include <stdint.h>

/* Product ABI shared by separately built applications and retained Recovery.
 * These values describe the already deployed format; do not reinterpret them.
 * Incompatible changes require a new version and an explicit migration. */
#define MOSAICO_RECOVERY_ABI 1U
#define MOSAICO_LAYOUT_VERSION 4U
#define MOSAICO_SYSMETA_PARTITION "sysmeta"
#define MOSAICO_OTA_NAMESPACE "iris_ota_demo"
#define MOSAICO_UPDATE_NAMESPACE "update"
#define MOSAICO_UPDATE_RESULT_KEY "last_result"
#define MOSAICO_SYSMETA_MAGIC 0x49535953U
#define MOSAICO_SYSMETA_VERSION 2U
#define MOSAICO_OPERATION_ID_BYTES 16U

typedef struct {
    uint32_t magic;
    uint32_t version;
    uint8_t operation_id[MOSAICO_OPERATION_ID_BYTES];
    int32_t result;
    uint8_t reserved[36];
} mosaico_sysmeta_record_t;

#ifdef __cplusplus
static_assert(sizeof(mosaico_sysmeta_record_t) == 64, "Mosaico sysmeta ABI size");
static_assert(offsetof(mosaico_sysmeta_record_t, result) == 24, "Mosaico sysmeta ABI offset");
#else
_Static_assert(sizeof(mosaico_sysmeta_record_t) == 64, "Mosaico sysmeta ABI size");
_Static_assert(offsetof(mosaico_sysmeta_record_t, result) == 24, "Mosaico sysmeta ABI offset");
#endif
