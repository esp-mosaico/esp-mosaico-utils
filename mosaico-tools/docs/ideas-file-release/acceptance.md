# File-release hardware acceptance records

Date: 2026-10-14. ESP-Mosaico / ESP32-S31, 16 MiB NOR; candidate firmware built with
ESP-IDF v6.2-dev-2221-g7b9cc1ac79f, Recovery ABI 2 and layout version 5.
Operations used an independent consuming workspace's mosaico.py; the repository reviewed bundle was not replaced.

## Test collection and identity

| Item | Recorded value |
| --- | --- |
| Hardware MAC | 30:ed:a0:f4:51:8e |
| Device ID | 4553502d49524953010030eda0f4518e |
| Ordinary test application | ideas_probe, 1.0.0 |
| Application code | 900001 |
| application_id | app-ae8474b27940440ebd0083b53635932c |
| release_id | release-f3b03c82d2da4242be3bb0e762c64c23 |
| ZIP | 842,492 bytes, 12 upload files |
| ZIP SHA-256 | 460a83039dcae58c1b0314a88a2cd77e2e0c92fffc4b4e37362ab63d3739c99a |
| Device root manifest SHA-256 | b45768629d36538602cd5f08ec882af0cafbacc0232c5b1ea5a5a69b53ae6bc3 |
| Vibe Mode ELF SHA-256 | 2c916878c8be0d0ff51062811f05b60600053d3c13e7cd8047f5f7949b389177 |

Repackaging identical author inputs produced the same ZIP digest. Website/bilingual resources froze from the ZIP; the server
derived the device root while preserving original inner Iris bytes. The HTTPS test server used a private CA;
device certificate/hostname verification stayed enabled, without TLS bypass.

## Completed checks

1. Booted candidate Vibe through mosaico.py recover from ROM Download Mode and confirmed hardware
   identity. Later candidates used existing maintenance deployment, without a new protocol self-update flow.
2. Single-ZIP upload returned 202, polling yielded a draft receipt, then publication was explicit. Device GET included
   profile/chip_id/flash_size/recovery_version, without resolve.
3. Preview created no test-code directory before confirmation. Confirmation saved complete firmware/, device/zh-CN/
   and device/en/. All 13 device files, including root, were read back and independently checked for lengths
   and SHA-256 against the fixed server release.
4. With the server stopped, Chinese/English system UI, list names and full names/descriptions switched offline.
   Language preferences survived another candidate boot; existing Wi-Fi credentials still connected.

5. With the server still stopped, Set as boot application installed NAND → NOR and verified all three
   components. From tap to observed "Boot application ready" took 378.6 seconds, including full
   validation, writing and index refresh; this is observed duration, not a precise benchmark.
6. mosaico.py iris restart booted ideas_probe 1.0.0 with Hello World displayed.
   New Boot ID: 15655661201906128565; normal-app mode, lifecycle_state=2,
   crash_count=0. It remained healthy after 70 seconds, with unchanged Device ID/hardware MAC.
7. mosaico.py iris test enter-recovery returned to Vibe, final Boot ID
   16889991520641364387, matching candidate digest, no crashes, automatic Wi-Fi and retained English
   preference. The test app remained the next boot target; the device stayed in Vibe.
8. Restarting the server preserved original fixed-release root bytes and strong ETag.
   Test origin: https://192.168.1.231:18444; device: 192.168.1.241.

Boot operation ID: d8def34a-4940-42e5-bd3f-abb31e526fdd. Pre-install candidate Vibe
Boot ID: 11810527603790164884. Only this task's Iris monitoring client was stopped; the test server
remained running for further integration. See the testing guide for startup/certificates.

## Automated validation

| Scope | Result |
| --- | --- |
| mosaico-tools/tests | 192 passed、24 skipped、51 subtests passed |
| Vibe Mode host tests, excluding native UI | 502 passed, 69 subtests passed |
| Native UI / GSP simulator | 16 passed; 2 Pillow deprecation notices |
| ESP-Iris Python tests | 604 passed |

Skipped tools tests were disabled real pre-commit environment checks. The independent consuming project completed real
application-bundle builds, bilingual resources and candidate Vibe builds. New public Iris entries retained
Python 3.8 syntax/standard-library import boundaries; mosaico-tools did not directly reference private installers.
All ESP-Iris Ruff checks passed under its Python 3.8 baseline (--target-version py38).
After final public-export ordering changes, the corresponding 35 public-API/firmware-bundle tests
passed again.

## Resources and boundaries

- Candidate Vibe: 1,774,160 bytes in a 1,835,008-byte slot, 60,848 bytes free.
- The 12 non-root device files totaled 1,416,957 bytes; the application image was
  1,295,904 bytes. At least 7,352 bytes of Ideas stack headroom were observed during installation.
- Existing 000001–000004 directories were retained. Reusing a code with another application_id
  was rejected; old data was not deleted to bypass identity checks.
- Full NAND verification/installation dominated duration. Language switching, titles and previews
  used authenticated metadata and independently verified display resources without rereading firmware. Boot scanning, commit
  and installation still performed complete checks.
- The local server implements the protocol for one test account. Production accounts/review/revocation, 100 MiB
  concurrency stress, maximum display combinations and physical power-loss endurance need separate acceptance.

See [integration steps](testing.md). Private certificates, tokens, server databases,
real builds and device evidence reside outside the repository in test/mosaico-ideas-e2e.
.codex-runs/acceptance.json summarizes receipts, identities and per-file hashes, linking screenshots/logs.
These local artifacts/credentials are not repository release resources.

## 2026-10-14 performance revalidation: P0, P1 and P2 internal-RAM buffers

This round added phase timings, separated stable refresh from fault recovery, reused complete preflight results,
and allocated a 4 KiB internal-RAM write block before erasure. No full-image PSRAM cache or parallel downloads.
These results supersede the earlier statement that boot scans read complete NAND firmware: stable boot scans read only
NAND descriptors/presentation resources and verify configured NOR; incomplete transactions undergo full recovery.

Same device, code 900001 and 1,295,904-byte application image:

| Phase | P1 + 4 KiB PSRAM control | P1 + 4 KiB internal RAM |
| --- | ---: | ---: |
| Complete preflight | 61.94 s | 60.17 s |
| Installation NAND application reads | 45.39 s | 43.84 s |
| Application NOR write calls | 39.45 s | 9.97 s |
| Application erase/component initialization | 3.60 s | 3.63 s |
| Application NOR readback/image checks | 10.97 s | 10.98 s |
| Complete installation, including preflight/final refresh | 184.59 s | 149.32 s |

Changing only write-block placement made NOR writes about 3.96 times faster and reduced total installation by about 19%.
The prior UI-observed 378.6 s depended on polling granularity; final device timing this round was
about 149.3 s, an overall reduction of about 61%. These are individual measurements, not maximum-throughput guarantees.
NAND reading remained the main cost; NOR write rate is not end-to-end download/install speed.

Automated validation: combined mosaico-tools/Vibe host tests **698 passed, 24 skipped,
120 subtests passed**. Added checks for actual I/O counts, corrupt-source rejection, incomplete-transaction rollback,
allocation failure before erasure, tail blocks and write/verification failures. ESP32-S31 with verified
ESP-IDF 6.2 built successfully. Final image: 1,777,296 bytes, 57,712-byte slot headroom.
Reviewed prebuilt bundle unchanged.

The test maintenance bundle was repackaged against readback table `3c26b245…2fd12`, containing Vibe only.
Initial source-layout mismatch was rejected without writing. After installation, reboot/reenter Vibe to release
existing commit state. Final deployment encountered a PC connection-acceptance timeout; evidence was retained and only this task's
Gateway connection recreated. Read-only operation reconciliation returned `observed_success`, without reflashing.
Final candidate ELF SHA-256:
`9bd8b5133931d37b2573b5aab2571a1882eb940c2334a1f98a29f13e80dd5a7d`。

Workspace `.codex-runs/performance/` retains both builds, timings, identities and receipts;
`comparison.json` supplies the table and `internal-reconciliation.json` records deployment acceptance.

Publishing the same ZIP separately as 900002 produced a successful download taking 167.30 s, excluding preview.
Application HTTP/persistence took 19.89 s: read wait 2.40 s, NAND fwrite 11.65 s. Its subsequent
persisted digest check took 44.99 s; format checks still reread the image separately. All 12 content files had one
successful device SHA-256 readback record. USB root readback matched server bytes exactly,
with root digest `c147c9e3e611d2f609706bc15916d5419f29a7cca7d0166cb0b5610f52b3d9cb`.
`download-verification.json` distinguishes device per-file hashing from USB root-byte readback.
Final directories contained only current/.roots and retained all older codes.
With the server paused, Chinese/English system UI and 900002 names/descriptions switched/displayed offline;
Chinese and the test server were restored afterward.

Installed ideas_probe 1.0.0 booted with Boot ID `3629005098614598359`, ran
61.45 s with crash_count=0, then returned to final Vibe, Boot ID
`17729294162040229863`, matching ELF and crash_count=0. The performance summary is in workspace
`performance/acceptance.json`, linked from the original acceptance summary.

## 2026-10-14 NAND counters, page cache and short transactions

This round added physical SPI/logical-page counters, a 64 KiB PSRAM logical-page LRU cache and short NAND-transaction
polling. The cache sits between LittleFS and Dhara; writes, erase, ioctl, sync and read errors
invalidate it. Data reads still use interrupts/DMA. NAND disk format, ECC and 40 MHz SIO remained unchanged,
without full-image caching, QIO or clock increases.

To isolate worker-state effects, a separate read-only component read the same 1,295,904-byte
image with tasks pinned to CPU 0/1, testing paused rendering, normal UI and
10 Hz text refresh twice per core. Cached variants first read another larger-than-cache file to evict target pages.
The table reports cumulative `fread`, excluding SHA-256, open/close and installer yields.

| Configuration | Samples | Mean read | Range | Physical page reads |
| --- | ---: | ---: | ---: | ---: |
| No cache, original SPI transactions | 12 | 8.821 s | 8.587–9.425 s | 39,081–39,082 |
| 64 KiB cache, original SPI transactions | 12 | 0.732 s | 0.706–0.781 s | 2,365 |
| 64 KiB cache, short-transaction polling | 12 | 0.685 s | 0.657–0.740 s | 2,365 |

All 36 lengths/SHA-256 values matched, with zero logical-read/SPI errors. The file generated 6,878 logical-page
requests and 6,232 cache hits; physical reads include Dhara mapping metadata. Caching reduced physical reads
about 94%, the main gain. Short transactions reduced read time another 6.4%; together,
mean reads were about 12.9 times faster. Optimized paused/normal/10 Hz UI times were 0.662, 0.681 and
0.711 s. UI load added about 7.4% here, insufficient to explain earlier multi-fold variation.

Normal Ideas tasks had no core affinity. Baseline/cache-only complete installations measured 33.05/59.93 s,
while NAND installation reads were 8.98/4.43 s and NOR/SHA phases also varied significantly. Causes
were unconfirmed, so neither these totals nor differences from the earlier 149.3 s can be attributed wholly to caching,
and controlled-read 12.9× speedup is not a complete download/install speedup.

Final production builds removed read-only probes and used 64 KiB cache plus short polling; image size
1,780,256 bytes, slot headroom 54,752 bytes. ELF SHA-256:
`8854df03646e4c3c2a68f57036c53b21d32583377c97d9f93296079c8f363562`。
Reviewed bundle unchanged. Host totals: **700 passed, 24 skipped,
120 subtests passed**. New ASan/UBSan coverage of actual cache/SPI wrappers included
concurrent reads, LRU, failed/partial-write invalidation, allocation failure, handle isolation and no error retries.

All three builds, per-sample counts, hashes and statistics reside in the consuming workspace's
`.codex-runs/performance/nand-optimization/`; `comparison.json` supplies the table.

The final candidate downloaded new release 900003 in **89.79 s**, excluding preview. Application
HTTP/persistence took 21.26 s, with 2.25 s HTTP wait and 13.87 s NAND fwrite. Persisted
digest verification took 10.34 s: NAND 4.86 s, SHA 3.82 s. All 12 device content files
passed hashing, followed by independent USB readback of all 13 including root, matching lengths/hashes to the
fixed release. Root SHA-256:
`95e4cd2f1767ffbe8ef4576f731dd97b1eb68a6284eb0410fdfb47c285e79b23`。
Only current/.roots remained; 000001–000004, 900001 and 900002 were retained.

With the server paused, 900003 Chinese/English names, descriptions and icons displayed offline, and system
language switching passed. Server/Chinese UI were restored afterward. Evidence: `download-metrics.json`,
`device-files-verified.json` and `offline-*.png`.

Code 900001 installation on final normal firmware took **60.80 s**, including 13.23 s preflight;
application NAND 4.64 s, SHA 3.81 s, NOR writes 9.93 s, initialization/erase 3.61 s,
NOR readback/image checks 10.97 s. All three components passed, with zero logical-read/SPI errors.
This again showed normal-task versus pinned-task timing differences. No affinity/scheduling changes
were added to normal tasks. Raw phases are in `install-metrics.json`.

Installed ideas_probe 1.0.0 booted with Boot ID `15833550933385061264`; after
84.03 s it remained normal, lifecycle_state=2, crash_count=0, then returned to final
Vibe, Boot ID `16591026631752702274`, matching ELF, no crashes and retained Chinese preference.
The device stayed in Vibe with the test application as boot target; the local server remained running.
`nand-optimization/acceptance.json` summarizes this round and links the previous two.

## 2026-10-14: Download phases, image-validation deduplication and slow-stack diagnosis

Still ESP32-S31, IDF `7b9cc1ac79f865983f59bb8ff3ff43eb74ff1dbe`,
64 KiB PSRAM NAND page cache, short polling, 40 MHz SIO and 4 KiB internal write buffer.
No release-protocol, digest, NOR readback or signature-check changes.

Download UI now progresses through transfer, verify files, check image, save and saved. Verification resets byte
progress and tracks actual processed content/file counts while hiding speed. Image/save phases
show status without fabricated percentages. Preview-fetched roots are excluded from the transfer denominator.
Both languages were checked. Failures stay in their phase; verification failures report "verified", not "transferred".

After NOR SHA-256 and complete image validation, application components record transaction-local
`image_verified`. Commit uses only that transaction's completed/verified target descriptor with
`esp_ota_set_boot_partition_skip_validate`, avoiding another full image check. New transactions clear the flag;
completed components cannot be rewritten. Readback/image failures prohibit app boot selection. IDF's boot-partition
selection and anti-rollback remain in their existing internals. Recovery's own pre-boot checks remain.

### Why normal tasks were much slower

ESP32-S31 currently enables `ESP_SYSTEM_ALLOW_RTC_FAST_MEM_AS_HEAP`; ordinary INTERNAL/8BIT
heaps include HP SRAM and LP/RTC RAM. Dynamically created 16 KiB Ideas stacks depend on contiguous-free-block
distribution; an internal buffer does not prove an HP SRAM stack. PSA software SHA state, local arrays and
storage-driver call stacks may therefore access slower RTC RAM.

Read-only controls used the same file, 4096-byte HP SRAM buffer and SHA implementation on CPU 0/1,
with default 8/16 KiB, forced 16 KiB SRAM and forced 16 KiB RTC stacks. All 24 NAND/NOR
records covered 1,295,904 bytes with SHA-256
`2ffd92edb1878aa7f3966688a285aa45a18b9c63fb0d5ca17e950c4f5f8047c5` and result code 0.
16 KiB SRAM versus RTC means: NAND reads 0.701/4.618 s, SHA 0.192/3.819 s;
NOR stack-buffer readback 0.153/2.620 s, SHA 0.194/4.064 s. Both cores agreed.

Normal UI then installed the same 900001. Ordinary candidate stacks were at `0x2f049xxx` SRAM;
the diagnostic candidate changed only stack capabilities to `0x2e003xxx` RTC. Both used 16 KiB,
priority 3, no core affinity, identical releases and this round's validation deduplication.

| Phase | Normal SRAM-stack candidate | RTC-stack control |
| --- | ---: | ---: |
| Complete installation | 14.839 s | 57.238 s |
| Complete file preflight | 3.915 s | 13.199 s |
| Application NAND reads | 0.710 s | 4.622 s |
| Application source SHA | 0.191 s | 3.805 s |
| Application NOR writes | 3.878 s | 9.957 s |
| Application NOR erase/preparation | 3.599 s | 3.593 s |
| Application NOR readback/SHA | 0.346 s | 6.689 s |
| One complete application image check | 0.261 s | 4.232 s |

Rows are not an exhaustive installation breakdown; NOR readback/image checks belong to component end.
Erase time barely changed, but CPU cost of reading, writing, SHA and image checking varied strongly with stack placement.
This explains most earlier fixed-task versus normal-task disparity and shows CRC16 replacement cannot remove
all overhead. Both original 60.802 s and this RTC 57.238 s include slow-stack costs; do not attribute
60.802 → 14.839 s entirely to deduplication. Deduplication removes the former commit's second image check,
about 4.2 s. This round also had another library Idea, changing metadata-scan duration.

**This round diagnosed slow stacks without changing production stack allocation. The 14.839 s result was that SRAM-stack run,
not a guarantee for every memory state.** Persistent HP SRAM implementation/acceptance follows below. RTC heap was not globally
disabled, nor was this addressed through affinity or different hash algorithms.

### Hardware, regressions and evidence

New release 900004 downloaded in 18.961 s: transfer 13.36 s, file checks 3.74 s, image check
1.39 s, save/refresh 0.47 s. Its actual stack was SRAM. Workspace-launcher readback of root
and 12 content files matched all fixed-release lengths/hashes and exact root bytes.
Saving was shorter than screenshot response time; native simulation checked saving UI and device logs checked
order. Device screenshots captured transfer, 32% file verification, image checking and saved state.

After installation, `ideas_probe` ran over 79 s with crash count 0, then returned to Vibe.
704 host tests and 120 subtests passed; 24 environment skips. All 18 native UI scenarios passed;
affected bilingual phases were rerun with added verification-failure coverage, totaling 19 distinct scenarios.
Final title cleanup separately passed all 34 Ideas worker tests.

Evidence: consuming test workspace `.codex-runs/performance/stages-and-runtime/`:
`runtime-samples.json`、`comparison.json`、`install-sram-metrics.json`、
`install-rtc-metrics.json`、`download.log`、`device-files-verified.json`、
`application-healthy.json`, `sim-zh/`, `sim-en/` and corresponding deployment/build records.
`ui-baseline/` retains the candidate used for complete timing; final changes only cleaned title assignment and
verification-failure percentages, under `final/`. Diagnostic firmware/forced RTC stacks are not final deliverables.

Final probe-free candidate: 1,802,832 bytes, 32,176-byte headroom; ELF SHA-256:
`e6109e7e897e21381792b73b3c1d8e2f8126ffe1406115bfe2c310de06594676`。
Deployment returned healthy/validated; final Boot ID `16701629094370671159`.
Physical layout SHA-256 remained `3c26b245870110b955f490e07fe047309b44b098c5adce18a449b1010bb2fd12`.
Existing identity, Wi-Fi, NAND and old crash evidence remained; reviewed bundle unchanged.

## 2026-10-14: Persistent HP SRAM worker and display DMA budget

After Wi-Fi starts, Ideas allocates one persistent 16 KiB INTERNAL/8BIT/DMA stack, keeping priority 3
and no affinity. A length-1 pointer queue serializes scans, previews, downloads, installation and language changes;
the worker waits between jobs instead of being recreated. Initialization publishes availability last; partial
allocation failures free everything, return ESP_ERR_NO_MEM and permit retry without RTC/PSRAM fallback.
Retaining the idle stack/control structures is this policy's memory cost.

Hardware also exposed display DMA contention: old candidates had LCD allocation failures too; persistent stacks could cause repeated refresh retries on language changes
and installation-result pages. BSP originally requested 7680-byte blocks with queue depth 10; IDF aligns
descriptors and frees temporary DMA copies when transaction results are reclaimed, so completed-but-unreclaimed blocks still consume memory.
Vibe now requests 3840-byte bus blocks and depth 1 only for onboard LCD, about 4 KiB temporary data
plus allocator/transaction overhead, retaining frequency, wiring, PSRAM DMA and NAND settings.
BSP/IDF sources remain unchanged. Reduced queue overlap is the tradeoff; full-screen transfers may still exceed one TE period,
without a 60 fps full-screen promise.

### Consecutive installations in one boot

Final candidate Boot ID `8968371995221683312`. Downloaded new 900006, then installed existing 900001
three times; between the last two, switched languages and opened/canceled local previews through normal UI.
24 completed task records covered these operations, all with HP SRAM `task_start` address `0x2f07744c`.
Minimum Ideas stack headroom: 7712 bytes; complete current-boot logs had no LCD submission/refresh errors.

| Phase | First | Second | Third |
| --- | ---: | ---: | ---: |
| Complete installation | 15.027 s | 15.024 s | 14.965 s |
| Complete file preflight | 3.943 s | 3.919 s | 3.935 s |
| Application NAND reads | 0.711 s | 0.711 s | 0.709 s |
| Application source SHA-256 | 0.192 s | 0.192 s | 0.191 s |
| Application NOR writes | 3.886 s | 3.903 s | 3.906 s |
| Application erase/preparation | 3.610 s | 3.641 s | 3.602 s |
| Application NOR readback/SHA | 0.351 s | 0.353 s | 0.350 s |
| Complete application image check | 0.263 s | 0.266 s | 0.261 s |

Each retained full preflight, source SHA, NOR readback SHA and one full image check.
Times stabilized around 15 s, removing dynamic-allocation fallback to slow RTC stacks in this flow. Three
samples do not guarantee latency for arbitrary network/storage/resource loads. Do not double-count parent/child phases.

Boot idle internal memory before LCD limits was 57443 bytes, versus final candidate 131447;
after consecutive operations, 118375, with a boot minimum of 38164. At each final-candidate task start,
largest contiguous HP SRAM was 63488 bytes. Free heap includes RTC; validate stack location by address/capabilities.

### Downloads, regressions and delivery evidence

900006 downloaded in 26.266 s: transfer about 20.50 s, file checks 3.77 s, image checks 1.14 s,
save/refresh 0.86 s. Application NAND writes took 9.525 s versus 900005's 2.335 s;
physical NAND page reads were also higher. New releases changed filesystem state, and this round did not isolate
write/reclamation costs. 26.266 s is not fixed download latency; slow-stack fixes do not cover that difference.

Post-save readback of root/12 files matched all fixed-release lengths/hashes.
The first attempt overlapped UI listing; file service returned 0x103 and host verification rejected incomplete results.
That evidence was retained; all 13 files passed after the device became idle. Logs/screenshots cover download,
verification, image checks, saving and completion; bilingual local previews/result pages passed hardware checks.

708 host tests, 120 subtests passed, 24 environment skips; 37 worker scenarios also passed
ASan/UBSan. New fixtures cover five initialization failures, cleanup/retry, one worker for 91 tasks,
immediate post-completion handoff and LCD limits preserving other SPI devices/SDK errors.
UI scenes/text were unchanged; display DMA was hardware-validated and prior native UI acceptance remains above.
A test-only RTC-stack variant compiled but was not deployed; final ELF has no automatic probes/forced RTC option.

Final candidate: consuming workspace
`.codex-runs/performance/persistent-sram-worker/lcd-budget/`, 1,803,424 bytes,
31,584-byte headroom; ELF SHA-256:
`363e641a5eb3b45897047c2588e797c934d6b4a88c6a08d5d402f5b1830ff760`。
`deploy.json` proves USB maintenance update from already-persistent-stack Vibe returned healthy/validated.
`install-metrics.json`、`current-boot.log`、`download-metrics.json`、
`device-files-verified.json` and screenshots preserve measurements. The parent directory retains the unlimited-LCD-queue
candidate/logs for memory review. Layout, identity and existing contents remained,
with reviewed bundle unchanged.

After the third install, `ideas_probe` booted with ID `6832000380832327817`; after 102.92 s,
normal mode, lifecycle_state=2, crash_count=0 and expected ELF remained. The consuming
workspace launcher returned to Vibe, final Boot ID `12816064771495800863`,
matching digest and crash_count=0; see `final-status.json` and `acceptance.json` in the same directory.
Wi-Fi credentials, Chinese preference and existing data remained; test server stayed running.


## 2026-10-14: Complete preview in one request

Preview switched to manifest GET multipart/related with current locale. Responses contain
root, firmware manifest and selected-language display/fonts/icon, streamed into bounded PSRAM
caches. Whole ETag, file lengths/SHA-256 and actual display content pass before confirmation enables.
Keep original root JSON/digest; whole-multipart ETag is not the root digest.

Test code 900007, release_id `release-50928c2f51cb4f7b972e06d7f19dd39a`.
Candidate maintenance deployment through workspace mosaico.py returned healthy/validated; physical layout
digest remained `3c26b245870110b955f490e07fe047309b44b098c5adce18a449b1010bb2fd12`.
Same-boot ID: `11097667958663235802`.

| Preview language | Body bytes | HTTP total | Preview task total | Requests |
| --- | ---: | ---: | ---: | --- |
| Chinese | 15513 | 0.636 s | 0.690 s | 1 manifest GET, 0 file GETs |
| English | 10472 | 0.550 s | 0.607 s | 1 manifest GET, 0 file GETs |

Both previews correctly showed names, descriptions, icons, versions and complete-set sizes. Chinese preview was canceled;
after switching language, English was requested. Confirmation fetched only 3 firmware components and 4 Chinese
display files, reusing cached English files/firmware manifest without refetching latest.
Complete download/validation/save took 18.921 s. Identical content at different paths could still be requested separately;
this verifies cached-path reuse, not cross-path SHA deduplication or arbitrary-network latency guarantees.

Readback of root/12 files matched all fixed-release lengths/SHA-256.
Preview minimum stack headroom was 8960 bytes, after download 7616; boot minimum internal RAM
was 42020 bytes. App NOR/boot target were unchanged; existing NAND/Wi-Fi remained.

Full host regression: 723 passed, 120 subtests, 24 environment skips. An additional whole-ETag mismatch
scenario brought worker coverage to 50 ASan/UBSan-passing scenarios; 41 server-protocol regressions passed.
Coverage included single-byte fragmentation, partial retry/cancel and rejection of missing/duplicate/wrong-path/language/length/digest parts,
oversized roots, duplicate headers, malformed MIME parameters and trailing content. OpenAPI YAML/JSON parsing
and patch-whitespace checks passed. UI layout did not change, so native UI suites were not repeated.

Clean ESP-IDF `7b9cc1ac79f865983f59bb8ff3ff43eb74ff1dbe` / ESP32-S31
build passed: candidate 1,805,440 bytes, headroom 29,568; deployed ELF SHA-256
`e107218e85731f8c75173be5afe9f0c8f003923aea1e42e1e1b79d61327c125a`.
Reviewed bundle unchanged. Complete build/deployment/server requests/screenshots/download logs and
readback evidence reside in consuming test workspace `.codex-runs/single-request-preview/`.
