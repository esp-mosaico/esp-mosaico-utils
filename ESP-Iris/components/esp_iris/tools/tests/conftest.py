"""Host unit tests never open a physical serial port."""
import pytest


@pytest.fixture(autouse=True)
def require_mock_serial(monkeypatch):
    try:
        import serial
    except ImportError:
        return

    def unexpected_serial(*args, **kwargs):
        raise AssertionError("Mock serial.Serial in host unit tests; use mosaico.py for physical devices")

    monkeypatch.setattr(serial, "Serial", unexpected_serial)
