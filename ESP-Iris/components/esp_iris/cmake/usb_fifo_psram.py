"""Separate TinyUSB CDC byte storage from internal stream/mutex/DMA state.

Adapt a generated build copy, never managed_components. Accept compatible
source layouts independently of their release, comments or whole-file hash.
The original copyright/license remain in the generated translation unit.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path


def adapt(source: bytes) -> bytes:
    text = source.decode("utf-8")

    def replace_once(pattern: str, replacement: str) -> None:
        nonlocal text
        text, count = re.subn(pattern, replacement, text, flags=re.MULTILINE)
        if count != 1:
            raise ValueError("Unsupported TinyUSB CDC layout for ESP_IRIS_USB_FIFO_PSRAM: "
                             "expected one matching declaration; disable this option or update the adapter")

    replace_once(r'^\s*#\s*include\s+"(?:class/cdc/)?cdc_device\.h"[^\n]*',
                 '#include "class/cdc/cdc_device.h"\n#include "esp_attr.h"')
    for direction in ("tx", "rx"):
        replace_once(r'\buint8_t\s+' + direction + r'_ff_buf\s*\[\s*CFG_TUD_CDC_' +
                     direction.upper() + r'_BUFSIZE\s*\]\s*;', '')
        text, count = re.subn(r'\bp_cdc\s*->\s*' + direction + r'_ff_buf\b',
                             'iris_cdc_' + direction + '_fifo[p_cdc - _cdcd_itf]', text)
        if not count or re.search(r'\b' + direction + r'_ff_buf\b', text):
            raise ValueError("Unsupported TinyUSB CDC FIFO references; disable ESP_IRIS_USB_FIFO_PSRAM "
                             "or update the adapter")
    replace_once(r'\bstatic\s+cdcd_interface_t\s+_cdcd_itf\s*\[\s*CFG_TUD_CDC\s*\]\s*;',
                 "static cdcd_interface_t _cdcd_itf[CFG_TUD_CDC];\n"
                 "// ESP-Iris: only FIFO bytes are external; DMA and mutexes stay internal.\n"
                 "static EXT_RAM_BSS_ATTR uint8_t iris_cdc_tx_fifo[CFG_TUD_CDC][CFG_TUD_CDC_TX_BUFSIZE];\n"
                 "static EXT_RAM_BSS_ATTR uint8_t iris_cdc_rx_fifo[CFG_TUD_CDC][CFG_TUD_CDC_RX_BUFSIZE];")
    return text.encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = adapt(args.source.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not args.output.exists() or args.output.read_bytes() != output:
        args.output.write_bytes(output)


if __name__ == "__main__":
    main()
