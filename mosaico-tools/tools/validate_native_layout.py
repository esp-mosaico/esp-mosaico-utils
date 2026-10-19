#!/usr/bin/env python3
"""Validate the product layout before IDF configures native flash targets."""
import argparse
from pathlib import Path

from prepare_system_update import IMMUTABLE_LAYOUT, _read_layout, normal_application
from mosaico_cli.product_contract import PRODUCT_CONTRACT


def validate(path: Path) -> None:
    layout = _read_layout(path)
    for label, expected in IMMUTABLE_LAYOUT.items():
        if layout.get(label) != expected:
            raise ValueError(f"native Mosaico flash requires the immutable {label} layout")
    normal_application(layout)
    for label, partition in layout.items():
        if label in IMMUTABLE_LAYOUT:
            continue
        if partition.offset < PRODUCT_CONTRACT["application_region_start"]:
            raise ValueError(f"{label} overlaps the retained prefix")
        if partition.type == "app" and partition.subtype in ("factory", "0", "0x0", "0x00"):
            raise ValueError("factory partitions override the normal ota_0 selection")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("partition_csv", type=Path)
    args = parser.parse_args()
    try:
        validate(args.partition_csv)
    except (OSError, ValueError) as error:
        parser.exit(1, f"native layout error: {error}\n")
