# SPDX-License-Identifier: Apache-2.0
"""Load Iris from a source example or an independently downloaded project."""
import sys
from pathlib import Path


def action_extensions(base_actions, project_path):
    project = Path(project_path).resolve()
    candidates = (
        project / "components/esp_iris",
        project / "components/espressif__esp_iris",
        project / "managed_components/espressif__esp_iris",
        Path(__file__).resolve().parents[2],
    )
    for component in candidates:
        tools = component / "tools"
        if (tools / "iris_usb_flash/__init__.py").is_file():
            if str(tools) not in sys.path:
                sys.path.insert(0, str(tools))
            from iris_usb_flash import action_extensions as extend

            return extend(base_actions, project_path)
    # The first reconfigure downloads managed dependencies. The next idf.py
    # invocation loads the extension; native build/flash actions remain usable.
    return {}
