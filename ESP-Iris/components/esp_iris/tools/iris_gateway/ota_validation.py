"""Validate OTA acceptance against the intended firmware identity."""

from __future__ import annotations

from typing import Any

from .operations import OperationOutcomeUnknown

OTA_VALIDATION_MODES = ("elf_sha256", "version")
DEFAULT_OTA_VALIDATION_MODE = "elf_sha256"


def _require_ota_validation_mode(value: str) -> str:
    if value not in OTA_VALIDATION_MODES:
        choices = ", ".join(OTA_VALIDATION_MODES)
        raise ValueError(f"OTA validation mode must be one of: {choices}")
    return value


def _validate_ota_identity(
    status: dict[str, Any],
    metadata: dict[str, Any],
    validation_mode: str,
) -> dict[str, str]:
    validation_mode = _require_ota_validation_mode(validation_mode)
    if status.get("project_name") != metadata.get("project_name"):
        raise RuntimeError("device reconnected with an unexpected firmware project")

    if validation_mode == "elf_sha256":
        expected_field = "elf_sha256"
        actual_field = "firmware_sha256"
        expected = str(metadata.get(expected_field, "")).lower()
        actual = str(status.get(actual_field, "")).lower()
        label = "firmware ELF SHA-256"
    else:
        expected_field = "version"
        actual_field = "app_version"
        expected = str(metadata.get(expected_field, ""))
        actual = str(status.get(actual_field, ""))
        label = "firmware version"

    if not expected:
        raise RuntimeError(f"OTA artifact is missing the expected {label}")
    if not actual:
        raise OperationOutcomeUnknown(f"device did not report its {label}; acceptance remains unknown")
    if actual != expected:
        raise RuntimeError(
            f"device reconnected with an unexpected {label}: "
            f"expected {expected}, got {actual}"
        )
    return {
        "mode": validation_mode,
        "expected_field": expected_field,
        "actual_field": actual_field,
        "expected": expected,
        "actual": actual,
    }
