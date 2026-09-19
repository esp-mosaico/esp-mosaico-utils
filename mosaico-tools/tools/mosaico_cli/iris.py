"""The single import boundary to the pinned, public Iris host API."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .errors import EnvironmentError


def host_api(workspace: Any) -> Any:
    tools = workspace.esp_iris_path / "components/esp_iris/tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    from iris_gateway import client

    if Path(client.__file__).resolve().parent.parent != tools.resolve():
        raise EnvironmentError("Another Iris checkout is already imported in this host process")
    if client.API_MAJOR != 1:
        raise EnvironmentError("Unsupported Iris public host API version")
    return client
