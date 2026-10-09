"""Separate TinyUSB CDC byte storage from internal stream/mutex/DMA state.

TinyUSB 0.21.0~2 has no storage-placement hook. Adapt a generated build copy,
never managed_components. Reject unreviewed upstream revisions explicitly.
The original copyright/license remain in the generated translation unit.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

CDC_SHA256 = "2ca9f63f5812e6fd58405e52b1bb282aa0752d1110fa577aca6442c1f67f4840"


def adapt(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != CDC_SHA256:
        raise ValueError("Unsupported TinyUSB CDC source for ESP_IRIS_USB_FIFO_PSRAM; "
                         "review the adaptation or disable this option")
    text = source.decode("utf-8")
    text = text.replace('#include "cdc_device.h"',
                        '#include "class/cdc/cdc_device.h"\n#include "esp_attr.h"')
    text = text.replace("  uint8_t tx_ff_buf[CFG_TUD_CDC_TX_BUFSIZE];\n"
                        "  uint8_t rx_ff_buf[CFG_TUD_CDC_RX_BUFSIZE];\n", "")
    text = text.replace("static cdcd_interface_t _cdcd_itf[CFG_TUD_CDC];",
                        "static cdcd_interface_t _cdcd_itf[CFG_TUD_CDC];\n"
                        "// ESP-Iris: only FIFO bytes are external; DMA and mutexes stay internal.\n"
                        "static EXT_RAM_BSS_ATTR uint8_t iris_cdc_tx_fifo[CFG_TUD_CDC][CFG_TUD_CDC_TX_BUFSIZE];\n"
                        "static EXT_RAM_BSS_ATTR uint8_t iris_cdc_rx_fifo[CFG_TUD_CDC][CFG_TUD_CDC_RX_BUFSIZE];")
    text = text.replace("p_cdc->tx_ff_buf", "iris_cdc_tx_fifo[i]")
    text = text.replace("p_cdc->rx_ff_buf", "iris_cdc_rx_fifo[i]")
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
