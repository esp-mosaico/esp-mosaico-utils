# Lifecycle stop, unregister, and restart

This dual-CDC USB example demonstrates a complete application-owned Iris lifecycle.
It starts with a small screenshot backend and RPC `0x1300/1`. Calling the RPC
queues work outside the Iris worker, lets the response drain, stops Iris,
unregisters both services, waits two seconds, re-registers them, and starts
Iris again.

## Standalone setup

Create this example from the Component Registry, then run the commands below
from its directory:

```bash
idf.py create-project-from-example "espressif/esp_iris=0.2.0:lifecycle"
cd lifecycle
```

With a source checkout, change to `ESP-Iris/components/esp_iris/examples/lifecycle`
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
idf.py -B build-lifecycle build
idf.py -B build-lifecycle \
  -p /dev/serial/by-id/<programming-port> flash
```

Start the Gateway, then request a cycle:

```bash
python esp_iris.py ctl rpc-raw \
  DEVICE_ID 4864 1
```

The programming console reports `RUNNING`, `STOPPED`, `UNREGISTERED`, and
`RESTARTED`. CDC0 disconnects and the Gateway discovers the same device again.
Do not run a screen capture while requesting the cycle; stopping Iris closes
active captures before the backend is unregistered.

Return to the [example index](../README.md).
