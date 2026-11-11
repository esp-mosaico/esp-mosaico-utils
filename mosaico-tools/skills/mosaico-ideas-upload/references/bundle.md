# Packaging Iris firmware and release ZIPs

Generate `system-update-bundle` with the consuming workspace's pinned ESP-IDF and ESP-Iris build environment.
`project package` and `project upload` do not build firmware. `iris system-update` writes to devices,
so it is not a packaging-only command. Check the application's existing build wrapper, or build only the target in a prepared IDF environment:

```bash
python "$IDF_PATH/tools/idf.py" -C "$PROJECT" -B "$PROJECT/build" \
  -D "ESP_IRIS_PYTHON=$IRIS_PYTHON" system-update-bundle
python mosaico.py project package --project "$PROJECT" --bundle "$BUNDLE" --output "$RELEASE_ZIP"
python mosaico.py project validate "$RELEASE_ZIP" --json
```

Paths and Python environments must come from the current consuming workspace; do not guess SDK or resource locations elsewhere.

Ordinary Idea `.irisfw` requirements:

- Unsigned, schema `esp-iris-system-update/0.2`, with a valid release.
- ESP32-S31, chip_id=32, with Flash capacity matching the target device.
- First component: 4 KiB partition table at 0x8000. Exactly one application, main_app at 0x210000; data components are allowed.
- Zero flags; no bootloader, recovery, credential or system-private partition images.
- Actual length, digest, target address and partition capacity match each component; preserve fixed product partitions.

`.irisfw` carries installation information; the outer release ZIP carries README, website assets and bilingual display resources.
The cloud supplies platform codes and application identity; neither upload layer includes them.

The build system packages only explicitly declared resource images. Trace how application resources are actually used:
C arrays and EMBED_FILES content already reside in the app; resources read from a separate runtime partition require
a corresponding data image. Website attachments/resources cannot replace device partition images.
Reserved unused or application-initialized partitions may omit initial images. Do not generate all-FF images merely to fill the file list.

If required runtime resources are missing, complete the build inputs before packaging. If only the display icon or optional description is missing,
continue under the best-effort rule; distinguish these cases. The packager preserves `.irisfw` unchanged.
Fix the actual source and regenerate after validation failure; never skip validation to upload.
