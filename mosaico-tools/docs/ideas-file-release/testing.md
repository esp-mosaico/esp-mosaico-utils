# Local file-release integration testing

The runnable protocol test server supports synchronous single-ZIP Agent upload, complete validation, draft replacement,
published-version deduplication, explicit publishing, capability-based selection, immutable manifests and content-addressed files.
It has one test account, without production accounts, review, revocation administration or deployment proxies.
For the actual ZIP → upload → publish → download → offline bilingual → install → boot results, see
[hardware acceptance records](acceptance.md).

## Host and server

Install dependencies from esp-mosaico-utils root; Python 3.10+, plus FreeType/libraqm for glyph generation:

```sh
python3 -m venv .venv-ideas
.venv-ideas/bin/pip install -r mosaico-tools/requirements-ideas.txt
.venv-ideas/bin/pip install -r ESP-Iris/components/esp_iris/tools/requirements.txt
```

Create test credentials; never commit generated private keys, tokens or state databases:

```sh
mkdir -p /tmp/ideas-test/tls
chmod 700 /tmp/ideas-test
openssl rand -hex 32 > /tmp/ideas-test/token
chmod 600 /tmp/ideas-test/token
openssl req -x509 -newkey rsa:2048 -nodes -days 14 -subj '/CN=Ideas Test CA' \
  -keyout /tmp/ideas-test/tls/ca.key -out /tmp/ideas-test/tls/ca.pem
openssl req -newkey rsa:2048 -nodes -subj '/CN=ideas-test' \
  -keyout /tmp/ideas-test/tls/server.key -out /tmp/ideas-test/tls/server.csr
# Replace 192.168.1.231 with the PC's actual LAN address.
printf 'subjectAltName=IP:192.168.1.231,IP:127.0.0.1,DNS:localhost\n' > /tmp/ideas-test/tls/extensions
openssl x509 -req -in /tmp/ideas-test/tls/server.csr \
  -CA /tmp/ideas-test/tls/ca.pem -CAkey /tmp/ideas-test/tls/ca.key -CAcreateserial \
  -days 14 -extfile /tmp/ideas-test/tls/extensions -out /tmp/ideas-test/tls/server.pem
chmod 600 /tmp/ideas-test/tls/*.key
PYTHONPATH=mosaico-tools/tools .venv-ideas/bin/python -m mosaico_cli.ideas_test_server \
  --state /tmp/ideas-test/state serve --host 0.0.0.0 --port 18444 \
  --token-file /tmp/ideas-test/token --cert /tmp/ideas-test/tls/server.pem \
  --key /tmp/ideas-test/tls/server.key
```

Host-only tests may omit TLS and bind 127.0.0.1; devices require HTTPS. Restarting with the same
state directory preserves drafts/releases; token rotation preserves the test account ID.
Default: four upload reception slots with synchronous validation. Configure production concurrency/proxy budgets separately.

## Package, upload and publish

Use the consuming workspace's own mosaico.py. Build the ordinary application's system-update-bundle first,
then prepare bilingual author configuration following the [CLI example](../../README.md#publish-a-mosaico-ideas-file-collection).
Populate `project.category_id` and repackage. The local protocol server provides neither a category catalog nor
existence/enabled/group validation; test ID `123` is acceptable. Production uploads require a real ID from the target site's public categories endpoint.

```sh
python mosaico.py project package --project projects/demo --output dist/release.zip
python mosaico.py project validate dist/release.zip --json
# Pass test tokens through the environment, not command arguments.
export MAKER_SPARK_TOKEN="$(cat /tmp/ideas-test/token)"
python mosaico.py project upload dist/release.zip --create --yes --json \
  --server https://127.0.0.1:18444 --ca-file /tmp/ideas-test/tls/ca.pem
unset MAKER_SPARK_TOKEN
```

Successful upload remains draft; device GET returns 404. Record public_id; first drafts lack app_number. Test administrators publish explicitly from esp-mosaico-utils root:

```sh
PYTHONPATH=mosaico-tools/tools .venv-ideas/bin/python -m mosaico_cli.ideas_test_server \
  --state /tmp/ideas-test/state publish PUBLIC_ID --author "Mosaico Team"
```

publish allocates app_number/release_id server-side and prints JSON; use app_number for device tests.
`--author` sets the root manifest's author display name, default `Mosaico Test Account`.
Download-schema validation applies; author freezes with original release bytes/digests. Later releases may use other names,
without rewriting existing releases. GET never backfills author into historical state.
The current Vibe Mode client still needs matching author-field support to receive these new releases.
For a new version, PATCH the same public_id then publish explicitly; duplicate published releases are rejected.
Test codes start at 201000. Isolate ranges across environments; never delete existing device NAND content for integration tests.
The new synchronous model uses agent_projects/agent_releases tables without reading/migrating old asynchronous upload records.

## Device flow

1. Set candidate firmware CONFIG_IRIS_FACTORY_IDEAS_SERVER_URL to the PC HTTPS origin and
   CONFIG_IRIS_FACTORY_IDEAS_CA_FILE to the absolute ca.pem path. Embed the CA while keeping certificate
   and hostname verification enabled; PC/device must share the LAN.
2. Install through the consuming workspace's existing mosaico.py deployment flow; use recover for ROM Download Mode.
   Verify hardware MAC, Device ID, Boot ID, candidate digest and ABI 2/layout 5.
   This does not publish Vibe self-update services or replace the repository's reviewed bundle.
3. Enter the published code. Network logs should show one manifest GET with locale and Accept: multipart/related,
   containing root, firmware manifest and selected-language display/fonts/icon; no file GET before preview.
   Show name, description, icon, version and size in the system language. Cancellation must not create
   a directory. Confirmation downloads firmware and both languages from the same pinned release.
4. Check manifest.json, firmware/, device/zh-CN and device/en under /nand/ideas/CODE/current;
   original bytes, sizes and digests must match the server snapshot. The .roots commit journal lives
   outside current. Download completion changes neither NOR nor boot target.
5. Stop the server, switch English/Chinese offline and inspect system UI, list names and local details.
   Preferences survive reboot. Only separately confirming "Set as boot application" installs NOR; start the app,
   verify same Device ID, new Boot ID and target version through mosaico.py, then return to Vibe.

All device data, screenshots, touch input and installation use the consuming workspace's mosaico.py. Direct-read
test extensions also use that launcher and Iris public file APIs, never direct serial access or user-partition erasure.

## Automated tests and coverage limits

```sh
python3 -m pytest mosaico-tools/tests
# Run Iris's own tests from its tools directory.
python3 -m pytest tests
python3 -m ruff check --target-version py38 iris_gateway tests
```

Host-only fixtures in mosaico-tools/tests/fixtures/ideas_release.py depend on no
consuming workspace and are not flashable release images. They cover ZIP/JSON/image/glyph/layout validation, HTTP
release isolation, repeated draft replacement, published-version deduplication, restart recovery, directory-fault recovery, preview cancellation, offline bilingual behavior, retry bounds and
list clicks. Host fault injection does not replace 100 MiB concurrency stress, maximum-resource combinations or physical power-loss endurance.

## Download and installation timing

P0/P1 and this P2 round cover phase timing, fewer duplicate reads per operation and a 4 KiB internal-RAM
NOR write buffer. Full-image PSRAM caching, multitask pipelines and parallel HTTP are outside this round.
Downloads still verify persisted per-file digests before firmware-format checks, which separately reread the application image.

`io_perf` reports microseconds in one summary per file/operation, not per-block logs:

| Record | Timing meaning |
| --- | --- |
| `http` | `read_us`: HTTP wait; `write_us`: NAND fwrite; `sync_us`: flush/fsync/close; bytes includes retries |
| `nand_hash` | NAND reads and SHA-256 separately; total also includes open/close and yielding |
| `prepare` | Complete preflight and required directory recovery, reused directly for this installation |
| `nand_install` | read: NAND; hash: source digest; write: write call; begin includes initialization/erase; end includes NOR readback/image checks |
| `nor_hash` / `nor_image` | NOR readback hash and ESP image validation, respectively |
| `boot_nor_hash` | Boot/explicit-scan configured application integrity |
| `scan` / `operation` | List-refresh/full-task wall time; operation names use internal command/Idea codes |
| `memory` | Internal free/largest block/boot minimum, PSRAM free and current stack headroom |

buffer records actual pointer memory class/capacity. total includes subphases; **do not add parent and child records**.
Network retries, opens, directories, logs and scheduling are not forced into read/write stages. Instant NOR write
throughput does not replace end-to-end time from install tap to bootable state.

Stable catalog scans do not read NAND firmware; incomplete transactions still undergo complete recovery. Installation reads firmware twice
(preflight/install), retaining source hash, NOR readback and image checks. Successful refresh does not reread
NAND firmware or NOR images. Internal-RAM allocation must fail before that component's erase begins.

Device A/B tests use the same device, downloaded Idea and P1 flow, changing only the installer's
4 KiB buffer memory class. PSRAM variants are temporary workspace builds; final sources/devices must
return to internal RAM. Save both ELFs, maintenance bundles, logs, Boot IDs and phase timings.
Maintenance target_layout_sha256 must match the actual device table. If app installation changed it,
repackage offline using the verified app table; never disable layout checks or alter the device table merely to match.

### Download phases, validation deduplication and stack diagnostics

Download UI acceptance order: transfer → verify files → check image → save → saved.
During file verification, bytes/file counts advance and speed is blank. Image checking/saving must not fabricate percentages.
`ideas_stage` 0/1/2 marks file verification, image checks and save start. Completion is
`operation name=1/<code> result=0`. Saving may be shorter than screenshot capture, so use logs
and simulation together; a completion-page screenshot is not evidence of an active save.

Host tests cover phase order, no advancement on failure and no boot selection after image/NOR-digest failure.
Each installation should emit one app `nor_image` record; ota_0 commit selection must not repeat segment checks.
Retain NAND SHA, NOR readback SHA and complete image validation. Verification flags cannot cross transactions.

### Persistent HP SRAM worker

After Wi-Fi initialization, the production Ideas worker reserves a persistent 16 KiB INTERNAL/8BIT/DMA stack,
receiving serialized tasks through a length-1 pointer queue. Do not restore per-task creation to save idle memory or
fall back to plain INTERNAL on failure: ESP32-S31's ordinary internal heap may include slow RTC RAM.

`test_ideas_worker_host.py` uses a pthread blocking queue to run the real worker loop, covering resource cleanup/retry after initial
task/lock/queue/stack allocation and first enqueue failures, state rollback after runtime enqueue failures,
30 preview/cancel/scan rounds with one worker and handoff immediately after completion publication.
All 37 scenarios run both normally and with ASan/UBSan, faking SDK boundaries only, not Ideas tasks.

On one device boot, sequentially download a new release, switch languages, preview and reinstall the same Idea; verify
identical `task_start` addresses in HP SRAM. Retain phase timings, stack minima and free memory.
Also check Wi-Fi/TLS downloads, app boot and USB maintenance updates after returning to Vibe, ensuring the persistent
stack does not starve those paths. Host fixtures validate injected low-memory failures; one successful idle-device
installation cannot establish resource-exhaustion behavior or long-duration stress acceptance.

Also run `test_lcd_budget_host.py`, checking LCD limits leave NAND/other SPI devices, original
configuration and callbacks unchanged and propagate SDK errors. Confirm the final ELF includes both initialization
adapters, explicitly retained for LTO. During downloads, bilingual switching and repeated installs, inspect `panel_io_spi_tx_color`, `TE ticket`
and `Display render failed` errors. Simulation has no real LCD DMA allocations and cannot replace
this check. Scope logs to the current boot; Gateway snapshots may retain errors from older candidates.


## Single-request preview regression

See [single-response preview format](preview-response.md). Device ideas_multipart.c
streams parts into PSRAM and checks referenced lengths/SHA-256, not ETag.
Confirmation downloads only firmware and the other language; save the root as original JSON bytes.

Protocol host tests use an independent MIME parser to check Chinese/English dependency sets, original bytes,
digests, release isolation and parameter rejection in actual HTTP responses. Worker tests cover request counts, single-byte fragmentation, partial-response
retry, cancellation, missing/duplicate/wrong-language/path/length/digest parts, oversized headers, trailing content and offline bilingual behavior.
One normal preview makes 1 manifest request and 0 file requests.
