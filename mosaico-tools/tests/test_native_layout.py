from pathlib import Path
import sys

import pytest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS / "tools"))
from validate_native_layout import validate


def test_template_native_layout():
    validate(TOOLS / "templates/hello_world/partitions.csv")
    validate(TOOLS / "templates/blank_game/partitions.csv")


@pytest.mark.parametrize("old,new", [
    ("app,  test", "app,  factory"),
    ("0x20000,  0x1c0000", "0x30000,  0x1b0000"),
    ("0x210000", "0x10000"),
])
def test_native_layout_rejects_retained_prefix_or_default_target_changes(tmp_path, old, new):
    original = (TOOLS / "templates/hello_world/partitions.csv").read_text()
    assert old in original
    path = tmp_path / "partitions.csv"
    path.write_text(original.replace(old, new))
    with pytest.raises(ValueError):
        validate(path)


@pytest.mark.parametrize("label", ["main_app", "ota_0", "other_app"])
def test_native_layout_accepts_product_owned_ota0_label(tmp_path, label):
    original = (TOOLS / "templates/hello_world/partitions.csv").read_text()
    path = tmp_path / "partitions.csv"
    path.write_text(original.replace("main_app", label))
    validate(path)
