# Streamed file transfer

This dual-CDC USB example mounts the `storage` flash partition as a wear-levelled
FATFS volume and exposes only its `/files` mount through ESP-Iris. The logical
volume ID visible to the Gateway is `files`.

The example enables streamed upload and download, directory listing and
creation, rename, and safe deletion. It creates `README.txt` on the first boot
so a download is available immediately. Files persist across resets. If the
partition cannot be mounted, this example formats it; flashing a new partition
table can therefore erase previous example files.

## Standalone setup

Create this example from the Component Registry, then run the commands below
from its directory:

```bash
idf.py create-project-from-example "espressif/esp_iris=0.2.0:file_transfer"
cd file_transfer
```

With a source checkout, change to `ESP-Iris/components/esp_iris/examples/file_transfer`
from the repository root instead. These application USB examples require an SDK
supporting ESP32-S31; the release matrix uses the pinned IDF 6.2 revision.
After the first build downloads the component, prepare its bundled Gateway:

```bash
python esp_iris.py setup
python esp_iris.py doctor
python esp_iris.py web
```

The launcher uses an isolated cached environment and does not change the IDF
Python environment. Close the Gateway before flashing or monitoring its ports.

## Build and flash

```bash
idf.py \
  -B build-file-transfer build

idf.py \
  -B build-file-transfer \
  -p /dev/serial/by-id/<programming-port> flash
```

CDC0 carries text logs and Iris commands for stock `idf.py monitor`; CDC1
carries binary data. Close Gateway before monitoring the same console. Flash
through the board's ROM download interface.

## Exercise the example

Start the Gateway and open `http://127.0.0.1:8443/`:

```bash
python esp_iris.py web
```

Select the device and open **Files**. The `files` volume should contain
`README.txt`. Download it, upload a new file, create a directory, rename an
entry, and delete a file or an empty directory to exercise the service.

The FATFS backend used here does not advertise
`ESP_IRIS_FILE_VOLUME_ATOMIC_REPLACE`, so creating new files is supported but
overwriting an existing path is rejected. Delete or rename the old file first,
or use a backing VFS with verified atomic-replace semantics in your product.

Return to the [example index](../README.md).
