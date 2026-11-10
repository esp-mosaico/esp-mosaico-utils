# mosaico-tools software specification

| Item | Description |
| --- | --- |
| Revision | Edition 2: 0.2 implementation and validation status |
| Revised | 2026-10-09 |
| Status | 0.2 implemented; validation scope in section 11 |
| Product role | ESP-Mosaico project, build, device-operation and delivery tools |
| Target version | mosaico-tools 0.2.0 with ESP-Iris 0.2 devices and host |
| Compatibility boundary | No 0.1 interoperability; documented migration only, no runtime compatibility layer |
| Reference environment | Python 3.10+, ESP32-S31, ESP-IDF `7b9cc1ac79f865983f59bb8ff3ff43eb74ff1dbe` |

## 1. Purpose and module boundaries

mosaico-tools provides workspace entry point `mosaico.py`, project/game templates, build integration, device selection, product updates and evidence workflows. It uses ESP-Iris public host APIs and the Recovery product contract, without maintaining another device protocol, Flash-write policy or reserved-firmware implementation.

- The [ESP-Iris specification](../../ESP-Iris/docs/esp-iris-software-spec-zh.md) owns console, control/data links, Gateway, Workbench, generic RPC, media, files, diagnostics and host APIs.
- The Vibe Mode specification owns Vibe Mode, partitions, boot, application-adapter ABI, product update backends and base bundles.
- This specification owns project entry points, default workflows, native-tool interoperability, operation orchestration, user prompts and documented 0.1 → 0.2 migration.

"Must" and "must not" denote acceptance requirements. Command help, README and public integration guides reflect 0.2 arguments, outputs, configuration and artifacts; specification prose does not replace hardware validation.

## 2. Confirmed requirements

| ID | Requirement |
| --- | --- |
| TOOL-BR-01 | Mosaico projects default to `mosaico.py` updates while allowing standard `idf.py flash monitor` and OpenOCD/JTAG. |
| TOOL-BR-02 | Original monitor requires no tools installation, Iris extension or Gateway; third-party projects require no partition-table changes or Iris integration. |
| TOOL-BR-03 | Monitor and Gateway exclusively share a control port; release must not trigger automatic reacquisition or require global protocol-mode switching. |
| TOOL-BR-04 | Discover and validate data endpoints automatically, without manual port pairing or control-link data confirmation. Initial credential setup still follows authorization requirements. |
| TOOL-BR-05 | Without a data link, retain on-demand screenshots, RPC and logs; clearly report unavailable continuous media, file and firmware Iris transfers. |
| TOOL-BR-06 | Expose Gateway UART/Serial-JTAG reconnect, boot-log capture and hardware reset to CLI/Workbench through public APIs. |
| TOOL-BR-07 | Preserve project creation, build, simulation, default update, recovery, evidence, device collaboration and application upload capabilities. |
| TOOL-BR-08 | Tools and matching Iris move to 0.2 without old protocols, configuration conversion, path forwarding, command compatibility aliases or automatic downgrade. |

## 3. Projects, templates and builds

### 3.1 Project ownership

| ID | Specification |
| --- | --- |
| TOOL-PROJ-01 | User projects live in host-workspace `projects/`, with workspace settings in `.mosaico.json`; this module owns public templates, tools and configuration schemas. |
| TOOL-PROJ-02 | `project init` uses this module's Hello World template; `game create` uses public game templates or explicitly selected complete BSP examples, never copying Vibe Mode as a user application. |
| TOOL-PROJ-03 | Check names, target directories, dependencies and template parameters before creation; support preview, roll back failed creation and never overwrite existing projects. |
| TOOL-PROJ-04 | Project creation needs no device; template-only creation needs no configured ESP-IDF build environment. Builds and simulation check their own dependencies. |
| TOOL-PROJ-05 | Portable templates use declared path anchors and version constraints. Manage GSP, game-engine and BSP dependencies per template, without mixing Vibe Mode's independent dependencies. |
| TOOL-PROJ-06 | Preserve build, resource generation and simulator entry points. Validate shared UI/game logic; simulation success cannot replace flashing, USB or JTAG hardware results. |

### 3.2 Application integration and environment checks

`doctor` and build integration validate Python, exact SDK revision, target support, dependencies, effective sdkconfig and product contracts. The reference workspace uses the pinned SDK above; generic Iris support is maintained separately, without imposing the product's fixed SDK version on Iris specifications.

Ordinary applications integrate the public Recovery adapter, default updates through Vibe Mode, product role/board/layout/ABI declarations and external-resource builds. Tools read the Recovery release contract rather than duplicating hardcoded partition addresses. Reused build artifacts still require configuration, layout and hash checks.

S31 product templates and acceptance firmware use QIO consistently with Vibe Mode and the bootloader. Tools check actual `CONFIG_ESPTOOLPY_FLASHMODE_QIO=y`, including reused builds. Do not misinterpret the SDK's ROM-load-stage `--flash-mode dio` as DIO runtime configuration or forcibly override it.

CMake still generates System Update artifacts, but 0.2 no longer blanket-rejects `flash`/`app-flash`. Generate native targets conforming to Recovery boot contracts and validate complete write lists. Removing the error without fixing target selection and bootloader behavior is insufficient.

## 4. Device access and host lifecycle

### 4.1 Gateway and clients

| ID | Specification |
| --- | --- |
| TOOL-GW-01 | CLI, Workbench and Agents for one project share a Gateway. Clients maintain independent liveness; one client exiting must not stop others or active writes. |
| TOOL-GW-02 | Exit according to published policy when no clients/tasks remain. Long operations retain executor/lock lifetime; command wait timeouts do not mean completion or safe retry. |
| TOOL-GW-03 | Preserve passive host state, enumeration, live status, claim/release and takeover. History or passive-state queries must not connect automatically. |
| TOOL-GW-04 | Claiming a device is not permanent keepalive; explicit run entry points may keep services alive. Background work must not reclaim released devices. |
| TOOL-GW-05 | Invoke services, query operations and save artifacts through public Iris APIs. Original monitor accesses devices directly, without a tools proxy. |
| TOOL-GW-06 | JSON and exit codes remain stable and automatable, distinguishing host state, live device state, historical evidence, unsupported protocols, missing authorization and insufficient capabilities. |

### 4.2 Device selection, binding and exclusion

| ID | Specification |
| --- | --- |
| TOOL-DEV-01 | Honor explicit device, hardware identity or endpoint selections strictly; connection failure must not select another device. Auto-selection requires one eligible candidate. |
| TOOL-DEV-02 | Group endpoints by verified `device_id`; adjacent ports or a shared IP do not prove device ownership. |
| TOOL-DEV-03 | Iris owns independent data discovery/handshake. Tools consume binding results and show control/data availability without sending prior control confirmation. |
| TOOL-DEV-04 | Data may connect before control; verify device, boot, task, authorization and ownership before submission. Multiple links must not create multiple writers. |
| TOOL-DEV-05 | OS locks and same-user ownership records coordinate projects. Never force-stop another Gateway or close other clients to obtain a port. |
| TOOL-DEV-06 | Release devices/transports and stop reconnect before native tools. After they exit, reclaim only on user request, without blind automatic takeover. |
| TOOL-DEV-07 | Distinguish brief control disconnect from explicit release. Healthy data tasks continue/pause per declared policy; explicit handoff ends related tasks and releases locks. |
| TOOL-DEV-08 | During takeover, stop new mutations and wait for active writes. Timeout retains the original owner rather than killing the writer. Query/recover using original takeover/operation IDs instead of duplicating actions. |

Original monitor and Web/AI device operations need not run simultaneously. Exiting monitor or releasing Gateway is normal resource handoff, not a protocol-mode switch; add no host "enter Iris communication mode" command.

## 5. Logs, reset, screenshots and evidence

### 5.1 Logs and hardware reset

| ID | Specification |
| --- | --- |
| TOOL-LOG-01 | `logs` retains history, indexing, rotation and Follow, including pre-handshake raw serial logs; firmware without Iris may still be captured according to interface capabilities. |
| TOOL-LOG-02 | UART/Serial-JTAG reconnect to the same device and save raw bytes as soon as readable, without waiting for Iris. Show source, capture segment and identity confidence. |
| TOOL-LOG-03 | Provide read-first-then-reset capture without clearing receive buffers after reset. Claim complete bootloader logs only when interface coverage and actual capture show no loss. |
| TOOL-LOG-04 | Expose gaps from disconnect, USB reenumeration and overflow. Hosts cannot recover bytes the device did not retain; reconnect is not complete replay. |
| TOOL-LOG-05 | Provide normal reset, ROM download entry and attach-without-reset through Gateway target policies: DTR/RTS for UART and appropriate USB Serial/JTAG timing. |
| TOOL-LOG-06 | Hardware reset must not depend on Iris RPC. Report unavailable capabilities, busy ports and write conflicts. Ordinary reconnect/debug pause must not reset automatically. |

These are required 0.2 API/CLI capabilities. Detailed design determines new command names/arguments; illustrative names are not current executable commands.

### 5.2 On-demand screenshots and diagnostics

`screenshot` prefers the data link. With control only, read bounded chunks of a consistent snapshot, verify device/boot identity, offsets, lengths and integrity, then save image and metadata. Timeouts reflect object size, actual rate and progress. Support cancellation, release and explicit failure for incomplete artifacts.

A single RPC response limit is not a whole-image limit. Never assemble changing frames into one image. Switching from interrupted data transfer to control requires confirming the same valid snapshot, otherwise recapture and explain why. Slow UART may take longer; show path and progress. Original monitor does not reconstruct/display images.

Preserve `memory`, `crash`, `rpc`, `device-status`, `operation-status` and registered-service entry points. Enable control Core Dump export only when the device declares bounded diagnostic reads. Control-chunked screenshots do not imply generic file/firmware support.

### 5.3 Operations and evidence

| ID | Specification |
| --- | --- |
| TOOL-EVID-01 | Save Operations, raw logs, Artifacts and structured results tied to actual device, boot, configuration and artifact hashes. Cached/history displays cannot prove current health. |
| TOOL-EVID-02 | Successful updates require the same device, expected new boot, image identity, product contract and health. Port reappearance, upload success or reachable Vibe Mode is insufficient. |
| TOOL-EVID-03 | Failed queries and unknown operations retain truthful state. A successful query cannot turn a failed queried operation into success. |
| TOOL-EVID-04 | After timeout, crash or restart, query the original Operation. Terminal states are immutable; supplemental verification is linked evidence, never automatic rewriting. |
| TOOL-EVID-05 | CLI saves device screenshots directly. Workbench page screenshots are not device-image evidence. Credentials must not appear in output, logs or artifacts. |
| TOOL-EVID-06 | Native flashing outside these tools must not fabricate a managed Operation. User logs may be imported as external evidence with clear source and unverified portions. |

## 6. Update and recovery flows

### 6.1 Default update selection

| Situation | Default path | Prerequisites |
| --- | --- | --- |
| Application code only | `iris app-update` | Identical complete partition table, matching product contract and image role |
| New application, layout or external resources | `iris system-update` | Valid complete target plan, resources and product layout rules |
| No valid product firmware, return after third-party use, or cross-generation base installation | `recover` | Matching base bundle, usable ROM entry and confirmed hardware identity |
| Vibe Mode self-update | Dedicated product update bundle or base recovery | Explicit self-update support, single-copy risk and ROM fallback explained |

| ID | Specification |
| --- | --- |
| TOOL-UPD-01 | Preflight local projects, bundles and NAND sources by declared formats. Prepare, build and validate artifacts before device-write stages. |
| TOOL-UPD-02 | Do not disguise system-update as app-update by altering partition tables. Report both layouts and the appropriate path on mismatch. |
| TOOL-UPD-03 | Ordinary applications default to entering Vibe Mode, writing through the product backend, then verifying return to a healthy application. Do not duplicate the writer in applications. |
| TOOL-UPD-04 | Iris updates require an authenticated data link. Explain unsupported UART/Serial-JTAG-only configurations while allowing native ROM alternatives; never silently encode firmware into console traffic. |
| TOOL-UPD-05 | Update plans show component roles, ranges, sizes and hashes. Validate reserved regions/resources through the Recovery contract; ordinary applications do not replace maintenance firmware. |
| TOOL-UPD-06 | One executor holds the lock during active writes. Cancellation, timeout and Gateway/client exit follow the operation state machine; never kill writers or resubmit forcibly. |
| TOOL-UPD-07 | Different devices may operate independently; mutations on one device are serial. Automatic data binding does not bypass this rule. |

### 6.2 recover

`recover` prepares and installs a complete base bundle through ROM, writing matching bootloader, partition table, boot selection and Vibe Mode, then validating product services. Reviewed bundles are the default; source builds require explicit choice and do not automatically overwrite/replace them.

- Normal 0.2 devices may use live evidence for coordinated release and log preservation. Devices without Iris, older-generation devices and third-party firmware must support direct ROM entry without a prior Iris handshake.
- Select targets by ROM-readable hardware identity, recheck before writing and verify the same hardware/product identity after reenumeration. Separate flashing ports cannot be paired solely by proximity or cache.
- Save complete write logs, Operations and post-recovery evidence. Prepare bundles and preflight ranges before actual reset/write.
- No default chip erase or implicit destruction of credentials, identity or product data. Explicitly reconstruct incompatible cross-generation data within documented scopes.
- Timeout does not mean the executor stopped; query the original operation before further action. Physical ROM entry is the fallback when automatic entry fails, distinct from entering Vibe Mode.

0.2 recover may record operations in a local host service without requiring it to understand old Iris protocols. ROM download is not a 0.1 Iris compatibility layer.

## 7. Native IDF, JTAG and third-party projects

### 7.1 Mosaico projects

Generated projects retain direct `idf.py flash monitor` without starting Gateway. Build integration must generate matching bootloader, partition-table, otadata, application and resource write lists under the Recovery contract, documenting the distinct actual scopes of flash and app-flash.

Native application flashing must preserve matching base Vibe Mode firmware. For blank or incompatible devices, guides specify recover or a complete native installation list containing matching base firmware. Writing only main_app cannot establish base recovery. Default updates still follow section 6.

OpenOCD/GDB retain identification, halt, resume, stepping, breakpoints and memory access. Gateway releases conflicting ports and pauses reconnect. JTAG and monitor may coexist where hardware permits; debug pauses must not trigger automatic recovery.

### 7.2 Third-party projects

Third-party ESP-IDF examples supporting the chip use their own projects/partition tables and direct `idf.py flash monitor`, without Iris, Mosaico templates, public Recovery adapters or product update bundles.

This path may replace product bootloader, layout, Vibe Mode and data. Tools must not inject reserved-partition requirements. Document the effects; after Gateway releases the port, do not block native tools. Missing Iris responses from third-party firmware neither prove corruption nor justify fabricated product-health evidence.

Returning to Mosaico requires recover followed by the target application, without promising restoration of overwritten data. Validate this separately from native Mosaico-project flashing that preserves Vibe Mode.

## 8. Application artifacts, simulation and upload

| ID | Specification |
| --- | --- |
| TOOL-ART-01 | Projects, games, UI and external resources generate traceable artifacts from templates; firmware/layout/configuration/resource hashes link to update operations. |
| TOOL-ART-02 | Bundle builds use Recovery's 0.2 contract; ordinary application bundles cannot carry unauthorized maintenance firmware or arbitrary Flash writes. |
| TOOL-ART-03 | Preserve local simulator/resource-validation entry points with clear boundaries between simulation, board adapters and device backends. |
| TOOL-ART-04 | Preserve Mosaico Ideas draft uploads with README, covers, resources and attachments; constrain paths to the project and prevent escapes/credential disclosure. |
| TOOL-ART-05 | Draft upload does not publish, submit for review or flash devices. Server bundle contracts must match device generations; old artifacts cannot be resubmitted by changing version strings alone. |
| TOOL-ART-06 | Document regeneration for incompatible templates, configuration, upload services or artifacts. 0.2 keeps no old-schema converters. |

Upload services, simulation engines and resource formats have independent versions. Do not rewrite them merely because Iris moves to 0.2; identify changed public contracts in the release matrix.

## 9. 0.2 boundaries and documented migration

### 9.1 Non-interoperability rules

mosaico-tools 0.2 uses only matching Iris 0.2 Gateway/device APIs and new product contracts. It does not adapt old services, Gateways, bundles or configuration automatically. Protocol-independent logs and ROM paths may handle devices without calling old Iris APIs.

No legacy parsers, dual-protocol detection, automatic downgrade, old-command aliases, module forwarding, database upgrades or runtime configuration/layout conversion. Unchanged public command names may remain, without retaining old arguments or semantics.

Isolate 0.2 configuration, databases, tokens, pairing state and runtime directories from 0.1; do not read/rewrite old databases. Retain old logs/artifacts in original directories or archives; export through isolated old tools, never by bundling legacy export parsers in 0.2.

### 9.2 User migration guide

1. Record the old workspace/utils revision, hardware identity, firmware and layout. Export needed configuration, logs, Core Dumps, artifacts and application data using old tools, then stop the old Gateway and release ports.
2. Archive the old environment, install matching 0.2 tools/Iris and create separate configuration/state. Manually recreate `.mosaico.json` and connection settings under the new schema, without automatic database import.
3. Update old projects' public integration, partitions and ABI declarations according to new templates and the Vibe Mode specification; rebuild applications/resources. Replace removed script entry points without local compatibility forwarding.
4. Prepare a complete 0.2 base bundle and explicit retained/reconstructed data lists, then install through recover's ROM path. The new Gateway need not connect to old Iris first.
5. Verify the same hardware, new Vibe Mode boot and target product contract; pair again and recreate tokens/permissions under new rules before installing the ordinary application.
6. Verify the default update cycle, control screenshots, automatic data binding, boot logs/reset and native monitor without Gateway. Validate native flash/JTAG through product workflows.
7. Update automation for 0.2 CLI JSON, HTTP API, Operation and Artifact contracts. Retain old history as offline reference, separate from new runtime state.

Third-party projects continue using native IDF without application-integration migration; base recovery is needed only when returning to Mosaico. Published migration guides must include final paths, sample configuration, replacement entry points and actual commands. This specification invents neither unimplemented arguments nor automatic converters.

## 10. Acceptance and release conditions

| ID | Scenario | Passing condition |
| --- | --- | --- |
| TOOL-AC-01 | Project creation | Device-free app/game creation succeeds with valid dependencies/paths; conflicts never overwrite and failures roll back |
| TOOL-AC-02 | Unextended native tools | Monitor works without Gateway or Iris host installation; Mosaico native write lists are correct and JTAG works |
| TOOL-AC-03 | Default updates | app-update/system-update selected by prerequisites, correct resources, healthy same-device verification and complete evidence |
| TOOL-AC-04 | Ports and collaboration | Shared multi-client Gateway, stable explicit selection, no reacquisition after release, no writer killed by timeout/takeover |
| TOOL-AC-05 | Automatic data binding | Data discovered/validated before control without manual pairing; wrong identity/authorization rejected |
| TOOL-AC-06 | Control-only screenshots | UART/Serial-JTAG save complete images with identity/integrity checks while logs, cancellation and status remain available |
| TOOL-AC-07 | Boot capture | Read-before-reset, reconnect, raw logs and gap markers pass; hardware reset works without Iris firmware |
| TOOL-AC-08 | Third-party | Original projects native-flash/monitor without partition changes or Iris; returning uses recover and identity validation |
| TOOL-AC-09 | Cross-generation recovery | New tools install through ROM without understanding 0.1; old bundles/state are not converted and archives remain |
| TOOL-AC-10 | Errors and results | Stable failures, unknowns, timeouts, authorization/capability errors; queries never replay writes or fabricate success |
| TOOL-AC-11 | Tool regressions | Templates, builds, simulation, artifacts, file/media entry points, diagnostics and draft uploads retained |
| TOOL-AC-12 | Clean version boundary | No 0.1 compatibility/forwarding in source, dependencies or packages; release docs/examples use 0.2 contracts |

Record exact SDK/utils revisions, dirty state, environment, configuration, image/layout hashes, hardware identity, Boot ID, logs and results. Report project, host, Recovery, frontend and hardware separately; historical results in the three specification matrices are not 0.2 acceptance.

## 11. Implementation, validation scope and references

Old path-forwarding and identity-migration layers are removed. State directories use 0.2, project schema is 2,
and Gateway API is 2. Native flash-list checks replace blanket prohibition. Boot contracts for ordinary applications and the test
maintenance partition, schema 3 base bundles and default Mosaico updates have been validated.

Old three-board and nine-device acceptance records are absent from the checkout; consult Git history as needed.
JTAG was skipped as requested; external Bridge 0.2 services and other untested scenarios are marked separately. Standard monitor
requires no Iris extension. Document measured first-enumeration timing limitations after S31 High-Speed USB flashing.

- [Current tools guide](../README.md)
- [Current application integration](application-integration.md)
- [Current System Update build integration](../cmake/system_update.cmake)
- [Product contract](../../mosaico-tools/product_contract.json)
