# Local development

Commands below run from the repository root unless stated otherwise. Use an
existing Python environment with pytest; install dependencies only if missing.
Do not run the full table for one change. A filename or `file.py::test_name`
selects a check; `-k` can narrow scenarios further and must select at least one.
Replace owner/case placeholders with the affected name.

| Changed owner | Start with |
| --- | --- |
| Tools | Relevant `mosaico-tools/tests/test_<owner>.py` |
| Shared resources/fetch | Relevant `shared/ideas/tests` or `shared/gsp/tests` |
| Iris host/protocol | From `ESP-Iris/components/esp_iris/tools`: `python -m pytest -q tests/test_<owner>.py` (Python 3.8 compatible) |
| Workbench | From `ESP-Iris/components/esp_iris/tools/frontend`: affected Vitest test and `npm run build`; Playwright only for affected browser flows |

Host tooling or documentation changes do not require an IDF build.

## Integration / CI

Run broader checks when the changed contract crosses these owners, or in CI:

```sh
python tools/check_repository_layout.py
python -m pytest -q shared mosaico-tools/tests
# Separately, from ESP-Iris/components/esp_iris/tools:
python -m pytest -q --ignore=tests/e2e
```

Public host dependencies: `ESP-Iris/components/esp_iris/tools/requirements-test.txt`
and `mosaico-tools/requirements-ideas.txt`. Sanitizers are opt-in with
`IRIS_HOST_SANITIZERS=1` for supported host tests. Preserve complete CI and release
checks; ordinary edits do not invoke them automatically.

Hardware checks depend on the change: physical touch/rotation/display for UI,
USB reconnect for transports, and actual writes/interruption/recovery for storage
or updates. Product device operations use the consuming
workspace's `mosaico.py`;
standalone Iris validation uses its own Gateway/CLI and IDF examples.

## Iris component packages

Use Component Manager 3.1.0 in a separate publishing environment. Consumer
builds keep the Component Manager version supported by their SDK (the IDF 5.5
image requires 2.2.x); install the Iris runtime requirements there without
upgrading the SDK's Component Manager. Package checks operate on the archive,
without borrowing runtime files from the checkout:

```sh
compote component pack --project-dir ESP-Iris/components/esp_iris --name esp_iris --dest-dir /tmp/iris-package
python ESP-Iris/tools/check_component_package.py /tmp/iris-package/esp_iris_0.2.0.tgz --work-dir /tmp/iris-package-check
```

In an activated IDF environment, add `--build --target esp32h2 --transport usj`
to compile the isolated example. Use a different work directory for each SDK,
target and transport; reuse it for incremental checks. The checker overrides
only the example's Iris dependency to the unpacked archive, so unpublished
versions can be validated without uploading them.

Vibe Mode, ESP-Iris and ESP-Mosaico Tools use independent release tags:
`vX.Y.Z`, `esp-iris-vX.Y.Z` and `esp-mosaico-tools-vX.Y.Z`, respectively.

Authentication and staging setup follow the
[Component Manager publishing guide](https://docs.espressif.com/projects/idf-component-manager/en/latest/publish/how_to_authenticate.html).
Keep tokens in the credential configuration or protected CI variables, never
in source files or command output.
