# RPC handlers and cancellable jobs

This dual-CDC USB example registers two cataloged RPCs and one application-defined
long-running job.

| Operation | ID | Request | Response |
| --- | --- | --- | --- |
| `system.echo` | `1/1` | Arbitrary bytes | Exact request bytes |
| `system.info` | `1/2` | Ignored JSON object | JSON device/runtime summary |
| Start example job | `0x1100/1` | Empty | Four-byte little-endian job ID |

The job advances for about ten seconds. Only one example job runs at a time;
the standard Gateway job query and cancel paths exercise retained state and the
cancellation callback.

## Standalone setup

Create this example from the Component Registry, then run the commands below
from its directory:

```bash
idf.py create-project-from-example "espressif/esp_iris=0.2.0:rpc_jobs"
cd rpc_jobs
```

With a source checkout, change to `ESP-Iris/components/esp_iris/examples/rpc_jobs`
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
  -B build-rpc-jobs build

idf.py \
  -B build-rpc-jobs \
  -p /dev/serial/by-id/<programming-port> flash
```

CDC0 carries text logs and Iris commands for stock `idf.py monitor`; CDC1
carries binary data. Close Gateway before monitoring the same console. Flash
through the board's ROM download interface.

## Exercise the example

Start the Gateway, then use the Workbench RPC tools or CLI:

```bash
IRIS=esp_iris.py
python "$IRIS" ctl rpc DEVICE_ID system.echo --params '{"value":"hello"}'
python "$IRIS" ctl rpc DEVICE_ID system.info --params '{}'
python "$IRIS" ctl rpc-raw DEVICE_ID 4352 1 --payload '{}'
```

Decode the raw four-byte response as the job ID, then query or cancel it with
`ctl jobs` and `ctl cancel`. The example intentionally has no Wi-Fi, screen, or
OTA slot.

Return to the [example index](../README.md).
