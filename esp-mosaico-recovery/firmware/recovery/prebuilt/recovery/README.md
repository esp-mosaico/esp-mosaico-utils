# Recovery 0.1 prebuilt bundle

This bundle includes the retained bootloader's black-background, orange dotted
`mosaico` Logo. The Logo is bootloader-only: per developer request, the BSP LCD
handoff has been removed and Recovery's original BSP dependency
`3d5c451598aaffbda6f41895a0414dba4bac3505` restored. Applications reset and fully
initialize the panel as before; a brief black screen is accepted.

Recovery remains version `0.1`, embeds the production
`https://iris-bridge.esp-claw.com` Bridge Origin, and retains the software SHA1
configuration introduced for Wi-Fi in ESP-34. The base partition table and
initial OTA selection data are byte-for-byte unchanged.

`manifest.json` records clean utility source revision
`17c4e49a2f8630f8430f157a110bf32ee4878118`, offsets, sizes and SHA-256 of all
four images. The artifact publication commit follows that source commit.

## Build and package validation

On 2026-09-16 the revised Recovery source and the normal GSP application with
original BSP were rebuilt for ESP32-S31 with zero warnings. The complete
prebuilt bundle was atomically generated using `update-recovery-prebuilt`;
bootloader and Recovery bytes match the tested candidate exactly.

- Bootloader: 23,424 bytes (`0x5b80`); 1,152 bytes (`0x480`) remain in its fixed
  24 KiB range with ERROR-only logging.
- Recovery: 1,728,480 bytes, within the unchanged 1,835,008-byte factory slot.
- Partition table: 3,072 bytes at `0x8000`; initial OTA data: 8,192 bytes at
  `0x9000`; both hashes remain unchanged.
- Product bundle validation covers schema, image magic, layout, security,
  sizes and SHA-256.
- Recovery host tests: 170 passed plus 45 subtests. Workspace Logo, retained
  Recovery and System Update contracts: 15 passed.

Build environment: ESP-IDF revision
`7b9cc1ac79f865983f59bb8ff3ff43eb74ff1dbe`, Python 3.12.3, verified ESP32-S31
support. IDF has pre-existing local modifications; utility source is clean,
but this is not a fully clean release-build attestation.

## Revised candidate device acceptance

ESP-Mosaico v1.2, hardware MAC `30:ed:a0:f4:60:56`, Device ID
`4553502d49524953010030eda0f46056`, accepted the revised candidate through the
consuming workspace's product launcher:

1. `mosaico.py system-update` Recovery self-update, operation
   `b66cb7d5-4111-4c17-9534-3efb79a7017d`: new Boot ID
   `4535915794750695044`; healthy Recovery `0.1`; ELF SHA-256
   `5ea8a630c46510ef543c2fb1b75e04ff5438294f015ccfe518a50bc0aad5dee9`
   matches the image descriptor. Its native screenshot shows the update
   service ready.
2. Bootloader plus the device's unchanged GSP partition table, operation
   `dc8939b9-45fe-4775-a074-80a4f814530d`: new Boot ID
   `17054374632751076924`; full 24 KiB bootloader readback SHA-256
   `2898a255e85e4deba65124258b707d2e6c3ac79556bec37df5980d5f0f534c60`
   matches the padded candidate; partition-table hash is unchanged.
3. `mosaico.py install`, operation
   `4995c0af-4c24-41f4-a12a-eccd97b8bb30`: the same device returned to healthy
   `gsp_hello` built with original BSP, Boot ID `17232826971309806030`; ELF
   SHA-256 `03db05cef1edc9894af2228c394252608cf7f8d0da7269ddebb8d85075913914`
   matches the revised application image descriptor.

The first bootloader attempt (`84c4dca0-aab8-48f2-9e43-3f51467bf2c8`) timed
out at plan validation while a screenshot transfer was running. Read-only
reconciliation retained the uncertain outcome; Boot ID, bootloader hash and
last commit receipt remained unchanged, and no System Update job was present.
The subsequent operation above succeeded. The uncertain attempt is not counted
as acceptance evidence.

The developer previously physically observed the same dotted Logo drawing and
confirmed normal display behavior, before requesting removal of BSP handoff.
That observation is not a new physical observation of this revised candidate;
earlier handoff logs are not evidence for it. v1.0/v1.1 GPIO branches compile
but have not received physical acceptance.

No whole-flash erase, credential/identity overwrite, UI-resource overwrite or
layout migration was performed. The device kept its GSP table, whose retained
Recovery prefix matches this base bundle. Fresh complete-bundle ROM provisioning
was not repeated; unchanged base table and initial OTA data retain earlier
reviewed provisioning evidence in Git history.

Raw evidence is retained in the consuming Vibe workspace under
`.codex-runs/boot-splash-no-bsp-20260916/` and `.codex-runs/mosaico/`. Archive it
before a formal release.
