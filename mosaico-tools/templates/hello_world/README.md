# ESP-Mosaico Hello World

Created with `python mosaico.py project init my_app`.
The same GSP 1.10.4 scene and portable C UI run on PC and ESP-Mosaico.

From the workspace root:

```sh
python mosaico.py project sim --project projects/my_app --interactive
python mosaico.py recover
python mosaico.py iris system-update --project projects/my_app
```

Run `recover` before the first install on a blank or unverified device.
Use `system-update` for new apps or changed resources/layouts. Use `app-update`
only for code changes with an identical full partition table and resources.

To add an Iris UART link, run from the generated project directory with ESP-IDF
activated:

```sh
idf.py -B build-uart -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.application.defaults;sdkconfig.uart.defaults" build
```

For USB Serial/JTAG, replace `uart` with `usj` in the build directory and overlay
filename. These optional overlays retain the default transports. UART uses the
UART0 console pins at 115200 baud. Separate build directories keep each generated
`sdkconfig` independent; changing defaults does not override an existing config.

Application components:

- `components/app_config`: device-side shared configuration reads from Vibe Mode.
- `components/app_hello`: portable UI behavior and private controller state.
- `components/app_display`: BSP-to-GSP display and optional touch policy.
- `main`: device startup and dependency composition only.
- `components/app_hello/host`: desktop adapter and its separate CMake build,
  reusing the same controller and public header; excluded from the ESP32 build.
- `components/app_hello/ui/main.json`: authored scene; generated bindings and bundles stay in the build.

`project sim` discovers a unique scene under `components/*/ui/main.json` (or the
older root `ui/main.json`). With multiple scenes, select one using `--scene PATH`,
relative to the project. This previews only that scene; omit `--scene` to run the
PC backend and its compiled application behavior.

Dependency direction is `main -> app_hello -> ESP-GSP`,
`main -> app_display -> BSP/ESP-GSP`, and
`main -> app_config -> esp_mosaico_app_recovery`. No application component depends on
`main` or on its sibling. Public headers live in `include/`; private state stays
in implementation files. Each component README includes its contract and usage.

Device startup reads the saved `wifi_ssid` and `wifi_password` through
`app_config_load_wifi()` and the public `mosaico_shared_get()` API. Configure Wi-Fi
in Vibe Mode; shared values live in `sysmeta/shared` and remain available when
switching to an application. Startup logs availability only and clears the
temporary credentials. Missing or invalid configuration leaves the UI running.
Hello World does not start a Wi-Fi connection; use the loaded snapshot when
adding a device networking component. An empty saved password means an open
network; a missing password key means configuration is incomplete.

For API keys, tokens and other shared strings, configure a custom key in
Vibe Mode > Settings > Shared information and follow the example in
[`app_config`](components/app_config/README.md). Default to this public read path
for user-provisioned shared configuration. Keep secrets out of source and logs,
and preserve NVS on errors. The PC backend does not access device configuration.
[`AGENTS.md`](AGENTS.md) carries these conventions into generated projects.

When adding behavior, keep `main` as a composition root. Add cohesive `app_*`
components only for independent responsibilities, declare public/private CMake
dependencies explicitly, and keep the graph acyclic. Avoid cross-module globals;
pass handles, context and value snapshots. Keep each public API comment within
three lines, describing its purpose and key preconditions/results. Put detailed
ownership, lifecycle, threading and timeout contracts in the component README;
document units and ranges beside fields.
Third-party dependencies retain upstream names. Pins and workspace overrides live
in `main/idf_component.yml` and the root CMake configuration. Apply local patches
in a dedicated dependency checkout and select it with `override_path`; never edit
`managed_components/` in place.

Git, editor and hook entry files stay at the root; format rules, project policy
and setup instructions live in `tools/quality/`. See its README to enable hooks.
The `tools/quality/policy.json` prefix rule checks local application component names.
Architecture and API semantics also require code review; formatter/static-analysis
success alone does not establish those contracts.
