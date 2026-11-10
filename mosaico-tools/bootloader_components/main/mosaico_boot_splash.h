// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <stdbool.h>

/** Power the panel, clear it to black and publish LCD handoff state. */
bool mosaico_boot_splash_show(void);

/** Paint the Vibe Mode or IDEA art once the boot target is known. Call only
 * after mosaico_boot_splash_show() succeeded; failures are non-fatal.
 */
bool mosaico_boot_splash_draw(bool vibe_mode);
