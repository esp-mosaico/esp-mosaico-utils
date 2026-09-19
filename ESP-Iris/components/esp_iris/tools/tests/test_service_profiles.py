import asyncio
import json
import shutil
import struct
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from iris_gateway.protocol import Channel, MediaType, ProtocolError
from iris_gateway.service_profiles import (
    ENTER_RECOVERY_METHOD_ID,
    POINTER_METHOD_ID,
    POINTER_SERVICE_ID,
    RECOVERY_SERVICE_ID,
)
from iris_gateway.session import DeviceSession

COMPONENT = Path(__file__).resolve().parents[2]


def test_optional_profiles_share_ids_and_normative_payloads(tmp_path):
    vectors = json.loads((COMPONENT / "protocol/golden_vectors.json").read_text())["vectors"]
    vectors = {item["name"]: bytes.fromhex(item["payload_hex"]) for item in vectors}
    pointer = vectors["pointer_v1_begin"]
    assert struct.unpack("<HHIHH", pointer[:12]) == (POINTER_SERVICE_ID, POINTER_METHOD_ID, 1000, 12, 0)
    assert struct.unpack("<BBhhHI", pointer[12:]) == (0, 0, 319, 239, 0, 0x12345678)
    assert struct.unpack("<HHIHH", vectors["enter_recovery_v1"]) == (RECOVERY_SERVICE_ID, ENTER_RECOVERY_METHOD_ID, 1000, 0, 0)
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("host C compiler unavailable")
    source = tmp_path / "profiles.c"
    source.write_text('''
#include "esp_iris_service_profiles.h"
_Static_assert(ESP_IRIS_POINTER_SERVICE_ID == 0x1001, "pointer service");
_Static_assert(ESP_IRIS_POINTER_METHOD_ID == 1, "pointer method");
_Static_assert(ESP_IRIS_POINTER_MESSAGE_SIZE == 12, "pointer size");
_Static_assert(ESP_IRIS_RECOVERY_SERVICE_ID == 0x7fff, "recovery service");
_Static_assert(ESP_IRIS_ENTER_RECOVERY_METHOD_ID == 2, "recovery method");
int main(void) { return 0; }
''')
    subprocess.run([compiler, "-std=c11", "-I", str(COMPONENT / "include"), str(source), "-o", str(tmp_path / "profiles")],
                   check=True, capture_output=True)


@pytest.mark.parametrize("valid", [True, False])
def test_screen_description_closes_without_transferring_pixels(valid):
    async def scenario():
        session = DeviceSession.__new__(DeviceSession)
        description = {"width": 320, "height": 240}
        payload = session._encode_media_description(description) + struct.pack("<I", 320 * 240 * 2)
        session._request = AsyncMock(side_effect=[
            SimpleNamespace(type=MediaType.OPENED, payload=payload if valid else b""), None,
        ])
        if valid:
            actual = await session.screen_description()
            assert (actual["width"], actual["height"]) == (320, 240)
        else:
            with pytest.raises(ProtocolError):
                await session.screen_description()
        assert [call.args[:2] for call in session._request.call_args_list] == [
            (Channel.SCREEN, MediaType.OPEN), (Channel.SCREEN, MediaType.CLOSE),
        ]
    asyncio.run(scenario())
