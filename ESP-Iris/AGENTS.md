# ESP-Iris

`components/esp_iris/` owns the ESP-IDF component: `include/` public APIs,
`src/` implementation, `protocol/` wire specification and vectors.
`components/esp_iris/tools/` owns `iris_gateway/`, Python `tests/` and the
React/Vite `frontend/`. Examples are in `examples/`; hardware fixtures in
`test_apps/`. Generated builds, managed components and caches are not source.

Follow the root AGENTS.md and WORKFLOW.md. Run affected host tests from
`components/esp_iris/tools`, preserve Python 3.8 support, and run Ruff for changed
Python files. Workbench changes use affected Vitest tests and `npm run build`;
use Playwright for affected browser flows. Regenerate and commit `frontend/dist`
when frontend source changes. Install dependencies only when needed.

Use existing C/Python four-space and TSX two-space style, snake_case functions,
`esp_iris_` public C names, `iris_` internals, uppercase `ESP_IRIS_*` constants
and PascalCase React components. Preserve TypeScript strictness and double quotes.
Protocol changes must synchronize C, Python, `protocol/spec.md` and
`golden_vectors.json`. Keep credentials, tokens and keys out of source and logs.

Compile the affected fixture or `examples/minimal` when native component
changes need it, reusing a compatible build. Standalone Iris device validation
uses its own Gateway/CLI and IDF examples, without Mosaico Tools or private
product firmware. Product Recovery operations use the consuming workspace's
`mosaico.py`. Record target/transport and observed hardware results only when
hardware testing is in scope.
