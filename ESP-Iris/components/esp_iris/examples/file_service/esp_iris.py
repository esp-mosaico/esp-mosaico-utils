#!/usr/bin/env python3
"""Run the Gateway bundled with this example's resolved component dependency."""
import importlib.util
import sys
from pathlib import Path

project = Path(__file__).resolve().parent
for component in (project / "managed_components/espressif__esp_iris",
                  project / "components/espressif__esp_iris", project / "components/esp_iris",
                  project.parents[1]):
    entry = component / "esp_iris.py"
    if entry.is_file() and (component / "tools/esp_iris.py").is_file():
        spec = importlib.util.spec_from_file_location("iris_launcher", entry)
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        raise SystemExit(launcher.cli())
print("ESP-Iris is not installed. Run idf.py reconfigure in this example first.", file=sys.stderr)
raise SystemExit(1)
