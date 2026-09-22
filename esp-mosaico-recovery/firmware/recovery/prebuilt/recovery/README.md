# Recovery 0.1 prebuilt bundle

Refreshed on **2026-09-22** from source commit
`b520c0987c15242e4baba167d7741384e5079b8b`. The Recovery source was clean when
the manifest was generated (`source.dirty: false`). The build uses ESP-IDF
`v6.2-dev-2221-g7b9cc1ac79f-dirt`, ESP32-S31, ESP-GSP 1.4.0 and GSPC 0.5.0;
the IDF checkout's existing local modifications remain reflected in its version.
Recovery stays at version `0.1`, ABI 1, with the same retained partition contract.

This bundle includes the Download Ideas QR code and updated URL, OTA phase/rate/
progress display, PSRAM allocation and HTTPS throughput improvements, and the
compact splash bootloader with INFO logs on UART0 at 115200 baud. It also
separates ordinary progress from authorization, reuses HTTPS connections, bounds
final result delivery to two seconds after local persistence, and erases only
image-sized application ranges (full data-partition erase is retained).

| Image | Offset | Size |
| --- | --- | ---: |
| Bootloader | `0x2000` | 24,432 bytes |
| Partition table | `0x8000` | 3,072 bytes |
| Initial OTA data | `0x9000` | 8,192 bytes |
| Recovery | `0x20000` | 1,815,248 bytes |

The 1,835,008-byte Recovery slot has **19,760 bytes free**. Recovery is 2,368
bytes larger than the preceding prebuilt image. The bootloader has 144 bytes
free in its 24 KiB slot. The base partition table and initial OTA bytes are
identical to the preceding bundle; initial OTA data is erased (`0xff`) so the
base bundle starts in Recovery. `manifest.json` records every image's SHA-256.

## Artifact provenance

The Recovery image is the exact final, device-tested 20 KiB Bridge writer-stack
build. Its embedded ELF SHA-256 is:

`da24c5ce9a8ef8357fff7bf68cdeeef6d706efedd9df3a8a9e4302dafe29bce4`

The bootloader is the exact artifact installed and accepted on the device during
the Logo/INFO-log validation. Its executable content matches the current build;
the rebuilt file differs only in descriptor compilation time, image checksum and
appended digest. The accepted binary is retained to preserve its hardware-tested
identity. Its SHA-256 after padding the entire 24 KiB slot with `0xff` is:

`d46d0987d7c39faa035ac78537e93d8b0d37ad3f3455cc428fe70d97a217a054`

All four images and the manifest were staged atomically by
`tools/prepare_recovery.py`, the packer used by `update-recovery-prebuilt`, with
the accepted bootloader supplied as an explicit input. No individual image was
replaced inside a previously generated manifest. The standard reviewed-source
`mosaico-recover-prepare` target then validated and staged this complete bundle;
the product CLI's `load_bundle` accepted it and the staged bytes matched.

## Validation and limits

Device validation used Device ID `4553502d49524953010030eda0f4518e`, MAC
`30:ed:a0:f4:51:8e`, board v1.2. The previously accepted bootloader remains
byte-identical; the operator's Logo/INFO-log acceptance still applies.
Recovery self-update operation `0605faaa-7712-4841-90a5-2302f2a5fadc` verified
this exact ELF and a healthy Recovery, Boot ID `14007907387211421134`.

The same Recovery completed a real cloud update at 16:18:12 +08 on 2026-09-22,
then booted the expected healthy Hello World application, Boot ID
`12671786291924841716`, ELF
`e71682afd7d25ba0692769b51257103408ab23fc2cd115917ab487374165fcd0`.
The persisted cloud operation is `1b2a5f37bee9cda896178167f5321d3c`, result 0.
Bootloader and partition-table hashes were preserved. Plan acceptance to commit
was 17.600 seconds, versus 62.048 seconds in the previous successful sample.
For the 1,259,472-byte application, erase size fell from 13,565,952 to 1,261,568
bytes, with observed erase time falling from 7.717 to 3.101 seconds.

The production service still advertised control protocol 1 during this test.
The new protocol-2 /authorize service and device paths pass host fault-injection
and server transaction tests, but require deployment and a further cloud device
test together. The previous post-component progress failure path is removed;
this does not identify the unlogged HTTP/cancellation cause of the earlier
15:19 failure or prove reliability under every network failure.

Validation passed 306 Recovery host tests and 60 subtests, 12 native UI tests,
and three Bridge checks with ASan/UBSan. Fault injection covers dropped progress,
malformed/denied commit grants, expired authority, cancellation, connection reuse
across URLs, image-aligned erasure and reboot after a permanently blocked final
response. The Bridge server passed `go test -race ./...`, `go vet ./...` and a
binary build. Controlled power-loss and protocol-2 hardware fault tests remain
outside this validation. The package manifest/slot/hash and reviewed preparation
checks validate all four images together; ROM provisioning was not repeated.

Use the consuming workspace's `mosaico.py recover` for complete base provisioning
and its ESP-Iris update commands for normal applications. Preserve the live
application table when creating a Recovery-only self-update package. Maintain
all four bundle images and the manifest together when regenerating artifacts.
