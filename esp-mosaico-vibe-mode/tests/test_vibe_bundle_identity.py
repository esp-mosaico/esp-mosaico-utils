"""Exercise current-source packaging and preservation of reviewed bundle names."""

import importlib.util
import json
import hashlib
import struct
from pathlib import Path

import pytest

from mosaico_cli.recovery import load_bundle


PROJECT = Path(__file__).resolve().parents[1] / "firmware/vibe-mode"


@pytest.fixture
def packager(monkeypatch):
    tool = PROJECT / "tools/prepare_recovery.py"
    monkeypatch.syspath_prepend(str(tool.parent))
    spec = importlib.util.spec_from_file_location("vibe_packager", tool)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_bundle(packager, images, manifest):
    packager.validate(
        images, manifest, "esp32s31",
        {"bootloader": 0x2000, "partition_table": 0x8000,
         "ota_data": 0x9000, "recovery": 0x20000},
        0x1C0000, 0x210000, False, False,
    )


def test_reviewed_bundle_staging_preserves_original_identity(packager, tmp_path):
    reviewed = PROJECT / "prebuilt/recovery"
    manifest = json.loads((reviewed / "manifest.json").read_text())
    images = {name: reviewed / item["file"] for name, item in manifest["images"].items()}
    check_bundle(packager, images, manifest)
    output = tmp_path / "reviewed"
    packager.atomic_stage(output, images, manifest)
    assert load_bundle(output, "esp32s31") == manifest
    for name, source in images.items():
        assert (output / manifest["images"][name]["file"]).read_bytes() == source.read_bytes()


@pytest.fixture
def current_build(packager, tmp_path):
    images = {}
    for name, filename in packager.IMAGE_FILES.items():
        path = tmp_path / filename
        path.write_bytes(packager.bootstrap_image() if name == "ota_data" else
                         (PROJECT / "prebuilt/recovery/partition-table.bin").read_bytes()
                         if name == "partition_table" else b"\xe9test-image")
        images[name] = path
    config = tmp_path / "sdkconfig"
    lines = ["CONFIG_FACTORY_RECOVERY_FIRMWARE=y"]
    for key, value in packager.PRODUCT_CONTRACT["compatibility"].items():
        key = "CONFIG_IDF_TARGET" if key == "chip_target" else "CONFIG_ESP_IRIS_" + key.upper()
        lines.append(key + "=" + json.dumps(value))
    config.write_text("\n".join(lines) + "\n")
    description = tmp_path / "project_description.json"
    description.write_text(json.dumps({
        "project_name": "vibe-mode", "project_version": "0.2.1", "target": "esp32s31",
        "config_file": str(config), "git_revision": "test-idf",
    }))
    return images, description


def candidate_manifest(packager, current_build, tmp_path):
    images, description = current_build
    return packager.build_manifest(
        images, description,
        {"bootloader": 0x2000, "partition_table": 0x8000,
         "ota_data": 0x9000, "recovery": 0x20000},
        0x1C0000, 0x210000, tmp_path,
    )


def test_current_bundle_uses_vibe_mode_identity(packager, current_build, tmp_path):
    images, _ = current_build
    manifest = candidate_manifest(packager, current_build, tmp_path)
    check_bundle(packager, images, manifest)
    assert manifest["project"] == "vibe-mode"
    assert manifest["images"]["recovery"]["file"] == "vibe-mode.bin"
    output = tmp_path / "current"
    packager.atomic_stage(output, images, manifest)
    assert load_bundle(output, "esp32s31") == manifest
    assert (output / "vibe-mode.bin").read_bytes() == images["recovery"].read_bytes()
    assert not (output / "factory.bin").exists()


def test_current_bundle_rejects_old_build_cache(packager, current_build, tmp_path):
    _, description = current_build
    metadata = json.loads(description.read_text())
    metadata["project_name"] = "factory"
    description.write_text(json.dumps(metadata))
    with pytest.raises(packager.RecoveryImageError, match="must be built by the vibe-mode project"):
        candidate_manifest(packager, current_build, tmp_path)


def test_current_bundle_rejects_mismatched_filename(packager, current_build, tmp_path):
    images, _ = current_build
    manifest = candidate_manifest(packager, current_build, tmp_path)
    manifest["images"]["recovery"]["file"] = "factory.bin"
    with pytest.raises(packager.RecoveryImageError, match="unexpected file name for recovery"):
        check_bundle(packager, images, manifest)


@pytest.mark.parametrize("label,capacity", [("main_app", 0xdf0000), ("ota_0", 0x700000)])
def test_bundle_application_metadata_uses_product_subtype(packager, tmp_path, label, capacity):
    raw = bytearray((PROJECT / "prebuilt/recovery/partition-table.bin").read_bytes())
    checksum_offset = None
    for offset in range(0, len(raw), 32):
        if raw[offset:offset + 2] == b"\xeb\xeb":
            checksum_offset = offset
            break
        if raw[offset + 2:offset + 4] == b"\x00\x10":
            row = list(struct.unpack("<HBBII16sI", raw[offset:offset + 32]))
            row[4], row[5] = capacity, label.encode().ljust(16, b"\0")
            raw[offset:offset + 32] = struct.pack("<HBBII16sI", *row)
    assert checksum_offset is not None
    raw[checksum_offset + 16:checksum_offset + 32] = hashlib.md5(raw[:checksum_offset]).digest()
    path = tmp_path / "partition-table.bin"
    path.write_bytes(raw)
    assert packager.normal_application_partition(path) == {
        "name": label, "subtype": "ota_0", "offset": "0x210000", "size": hex(capacity),
    }
    raw[checksum_offset + 16] ^= 1
    path.write_bytes(raw)
    with pytest.raises(packager.RecoveryImageError, match="MD5"):
        packager.normal_application_partition(path)
