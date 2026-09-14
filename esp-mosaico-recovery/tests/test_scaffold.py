from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest import mock


TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "tools"))

from mosaico_cli.cli import main
from mosaico_cli.errors import EnvironmentError, OperationError, SelectionError
from mosaico_cli.scaffold import initialize_project
from mosaico_cli.workspace import load_workspace


class ScaffoldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.template = self.root / "projects" / "hello_world"
        self.template.mkdir(parents=True)
        config = {
            "schema_version": 1,
            "workspace": {"projects_dir": "apps/nested", "default_project": "projects/hello_world"},
            "dependencies": {"bsp": "vendor/bsp", "esp_iris": "vendor/iris"},
            "build": {"runner": "builtin"},
            "devices": [{"id": "esp-mosaico"}],
        }
        (self.root / ".mosaico.json").write_text(json.dumps(config), encoding="utf-8")
        self.workspace = load_workspace(TOOL_ROOT, explicit=str(self.root))
        contents = {
            "CMakeLists.txt": '''cmake_minimum_required(VERSION 3.16)
set(SDKCONFIG_DEFAULTS "sdkconfig.defaults;sdkconfig.application.defaults")
set(EXTRA_COMPONENT_DIRS
    "${CMAKE_CURRENT_LIST_DIR}/../../components/esp_mosaico_app_recovery")
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(hello_world VERSION 1.0.0)
include(../../cmake/system_update.cmake)
''',
            "README.md": "# ESP-Mosaico Hello World\n\n"
            "Hello World!\npython mosaico.py install --project projects/hello_world\n"
            "python mosaico.py system-update --project projects/hello_world\n",
            "partitions.csv": "# Keep exact bytes\r\nsysmeta,data,nvs,0xc000,0x14000,\r\n",
            "sdkconfig.defaults": 'CONFIG_IDF_TARGET="esp32s31"\n',
            "sdkconfig.application.defaults": 'CONFIG_ESP_IRIS_OTA_DEFAULT_VIA_RECOVERY=y\n'
            '# CONFIG_ESP_IRIS_OTA is not set\nCONFIG_ESP_IRIS_USB_PRODUCT="ESP-Iris Mosaico Hello World"\n',
            "main/CMakeLists.txt": 'idf_component_register(SRCS "main.c" REQUIRES esp_mosaico_app_recovery)\n',
            "main/idf_component.yml": '''dependencies:
  idf: ">=6.2"
  esp-mosaico-bsp:
    version: "*"
    override_path: ../../../submodule/esp-mosaico-bsp/components/esp-mosaico-bsp
  esp_iris:
    version: "*"
    override_path: ../../../submodule/esp-mosaico-utils/ESP-Iris/components/esp_iris
  lvgl/lvgl:
    version: ">=8,<10"
''',
            "main/main.c": 'static const char *TAG = "hello_world";\n'
            'void app_main(void) { iris_ota_support_start(); /* Hello World! */ }\n',
        }
        for filename, content in contents.items():
            path = self.template / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode("utf-8"))
        for filename in ("components/esp_mosaico_app_recovery/CMakeLists.txt",
                         "cmake/system_update.cmake", "tools/prepare_system_update.py"):
            path = self.root / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# shared resource\n", encoding="utf-8")

    def snapshot(self) -> dict[str, bytes | None]:
        return {str(path.relative_to(self.root)): path.read_bytes() if path.is_file() else None
                for path in self.root.rglob("*")}

    def test_creates_only_sources_and_preserves_template_and_workspace(self) -> None:
        for filename in ("build/app.bin", "managed_components/cache", "sdkconfig",
                         "dependencies.lock", "sdkconfig.old", "extra.txt"):
            path = self.template / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("local-only", encoding="utf-8")
        before = self.snapshot()
        result = initialize_project(self.workspace, "My_app2")
        project = Path(result["project"])
        self.assertEqual(result["status"], "created")
        self.assertEqual(project, self.root / "apps/nested/My_app2")
        self.assertEqual(len([p for p in project.rglob("*") if p.is_file()]), 8)
        for filename in ("partitions.csv", "sdkconfig.defaults", "main/CMakeLists.txt"):
            self.assertEqual((project / filename).read_bytes(), (self.template / filename).read_bytes())
        self.assertIn("project(My_app2 VERSION 1.0.0)", (project / "CMakeLists.txt").read_text())
        self.assertIn('TAG = "My_app2"', (project / "main/main.c").read_text())
        self.assertIn("Hello World!", (project / "main/main.c").read_text())
        self.assertIn("iris_ota_support_start()", (project / "main/main.c").read_text())
        self.assertIn("python mosaico.py recover", (project / "README.md").read_text())
        after = self.snapshot()
        self.assertTrue(all(after[path] == content for path, content in before.items()))
        self.assertFalse(self.workspace.run_dir.exists())

    def test_rebases_shared_and_component_paths_for_nested_projects(self) -> None:
        workspace = replace(self.workspace, projects_dir=self.root / "apps with spaces/nested")
        result = initialize_project(workspace, "demo")
        project = Path(result["project"])
        cmake = (project / "CMakeLists.txt").read_text()
        references = re.findall(r'"\$\{CMAKE_CURRENT_LIST_DIR\}/([^"]+)"', cmake)
        self.assertEqual({(project / path).resolve() for path in references}, {
            self.root / "components/esp_mosaico_app_recovery",
            self.root / "cmake/system_update.cmake", self.root / "vendor/iris",
        })
        manifest = (project / "main/idf_component.yml").read_text()
        overrides = re.findall(r"override_path: (.+)", manifest)
        self.assertEqual([(project / "main" / json.loads(p)).resolve() for p in overrides], [
            self.root / "vendor/bsp/components/esp-mosaico-bsp",
            self.root / "vendor/iris/components/esp_iris",
        ])
        self.assertIn('idf: ">=6.2"', manifest)
        self.assertIn('version: ">=8,<10"', manifest)
        self.assertIn("apps with spaces/nested/demo", result["install_command"])

    def test_dry_run_does_not_write_or_start_runtime(self) -> None:
        before = self.snapshot()
        output = io.StringIO()
        with mock.patch("mosaico_cli.cli.RunContext", side_effect=AssertionError("runtime started")), redirect_stdout(output):
            code = main(["init", "demo", "--dry-run", "--json", "--verbose", "--workspace", str(self.root)])
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(len(result["files"]), 8)
        self.assertEqual(before, self.snapshot())

    def test_rejects_bad_names_before_writing(self) -> None:
        before = self.snapshot()
        for name in ("", "../escape", "a/b", "a\\b", "1app", "app-name", "CON", "lpt1", "应用", "a" * 32):
            with self.subTest(name=name), self.assertRaises(SelectionError):
                initialize_project(self.workspace, name)
        self.assertEqual(before, self.snapshot())

    def test_rejects_existing_file_and_empty_directory(self) -> None:
        self.workspace.projects_dir.mkdir(parents=True)
        for name in ("file", "directory"):
            target = self.workspace.projects_dir / name
            if name == "file":
                target.write_text("keep", encoding="utf-8")
            else:
                target.mkdir()
            before = self.snapshot()
            with self.assertRaises(SelectionError):
                initialize_project(self.workspace, name)
            self.assertEqual(before, self.snapshot())

    def test_rejects_broken_symlink_destination(self) -> None:
        self.workspace.projects_dir.mkdir(parents=True)
        target = self.workspace.projects_dir / "demo"
        try:
            target.symlink_to(self.root / "missing", target_is_directory=True)
        except OSError:
            self.skipTest("Symlinks are unavailable")
        with self.assertRaises(SelectionError):
            initialize_project(self.workspace, "demo")
        self.assertTrue(target.is_symlink())

    def test_rejects_destination_outside_workspace_and_recovery_template(self) -> None:
        for workspace in (replace(self.workspace, projects_dir=self.root.parent / "outside"),
                          replace(self.workspace, init_template=self.workspace.recovery_project)):
            with self.assertRaises(SelectionError):
                initialize_project(workspace, "demo")

    def test_incomplete_template_fails_before_writing(self) -> None:
        (self.template / "partitions.csv").unlink()
        before = self.snapshot()
        with self.assertRaises(EnvironmentError):
            initialize_project(self.workspace, "demo")
        self.assertEqual(before, self.snapshot())

    def test_dry_run_rejects_a_file_in_the_destination_parent_path(self) -> None:
        (self.root / "apps").write_text("keep", encoding="utf-8")
        before = self.snapshot()
        with self.assertRaises(EnvironmentError):
            initialize_project(self.workspace, "demo", dry_run=True)
        self.assertEqual(before, self.snapshot())

    def test_ambiguous_template_rewrite_fails_before_writing(self) -> None:
        cmake = self.template / "CMakeLists.txt"
        cmake.write_text(cmake.read_text() + "project(hello_world)\n", encoding="utf-8")
        with self.assertRaises(EnvironmentError):
            initialize_project(self.workspace, "demo")
        self.assertFalse(self.workspace.projects_dir.exists())

    def test_crlf_template_is_supported(self) -> None:
        for path in self.template.rglob("*"):
            if path.is_file():
                path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        result = initialize_project(self.workspace, "demo")
        self.assertIn("project(demo VERSION 1.0.0)", (Path(result["project"]) / "CMakeLists.txt").read_text())

    def test_write_failure_cleans_created_files_and_parents(self) -> None:
        before = self.snapshot()
        original = Path.open

        def fail(path, mode="r", *args, **kwargs):
            if mode == "xb" and path.name == "main.c":
                raise OSError("simulated disk full")
            return original(path, mode, *args, **kwargs)

        with mock.patch.object(Path, "open", fail), self.assertRaises(OperationError) as caught:
            initialize_project(self.workspace, "demo")
        self.assertEqual(caught.exception.details["cleanup_errors"], [])
        self.assertEqual(before, self.snapshot())

    def test_concurrent_initialization_has_one_winner(self) -> None:
        def create():
            try:
                return initialize_project(self.workspace, "demo")["status"]
            except SelectionError:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: create(), range(2)))
        self.assertCountEqual(results, ["created", "conflict"])
        self.assertEqual(len(list((self.workspace.projects_dir / "demo").rglob("*.c"))), 1)

    def test_failure_cleanup_preserves_content_created_by_someone_else(self) -> None:
        project = self.workspace.projects_dir / "demo"
        foreign = project / "keep.txt"
        original = Path.open

        def fail(path, mode="r", *args, **kwargs):
            if mode == "xb" and path.name == "main.c":
                foreign.write_text("external content", encoding="utf-8")
                raise OSError("simulated disk full")
            return original(path, mode, *args, **kwargs)

        with mock.patch.object(Path, "open", fail), self.assertRaises(OperationError) as caught:
            initialize_project(self.workspace, "demo")
        self.assertEqual(foreign.read_text(), "external content")
        self.assertEqual(list(project.iterdir()), [foreign])
        self.assertTrue(caught.exception.details["cleanup_errors"])

    def test_cli_json_error_and_success(self) -> None:
        for name, expected in (("demo", 0), ("demo", 2), ("../outside", 2)):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = main(["--workspace", str(self.root), "init", name, "--json"])
            self.assertEqual(code, expected)
            result = json.loads(out.getvalue() if code == 0 else err.getvalue())
            self.assertEqual(result["ok"], code == 0)
            if code:
                self.assertEqual(result["error"], "selection_error")
                self.assertEqual(result["exit_code"], 2)


if __name__ == "__main__":
    unittest.main()
