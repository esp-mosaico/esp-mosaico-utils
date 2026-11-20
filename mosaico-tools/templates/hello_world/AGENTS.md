# Application development

Read the owning component and its README before editing. Keep `main` as the
device composition root and `app_hello` portable between device and PC.

For Wi-Fi credentials and other user-provisioned shared configuration, default
to Vibe Mode's shared information through the public `mosaico_shared_get()` API.
Use `app_config_load_wifi()` for the saved `wifi_ssid` / `wifi_password` pair;
see `components/app_config/README.md` for errors and custom-key examples.
Applications must work with the public Tools components alone: never import
private Vibe Mode sources or read its private namespaces as a fallback.

Keep credentials out of source, sdkconfig defaults, logs and UI diagnostics.
Treat a missing key as unconfigured; an explicitly empty Wi-Fi password means
an open network. Preserve the UI and Recovery when shared configuration is
unavailable. Ask users to configure it in Vibe Mode. Do not erase NVS to recover
from a read failure, write back defaults or create a second persistent copy.
Clear temporary credential buffers after use. Store application-owned state
separately from shared configuration.

Hello World demonstrates reading configuration. Add connection lifecycle and
retry behavior in a device networking component when the application needs it;
use `WIFI_STORAGE_RAM` for credentials obtained from shared information. The PC
backend has no device NVS; supply explicit test values at the platform boundary
when adding host-side consumers.

Declare CMake dependencies explicitly and run focused behavior checks. Device
operations use the consuming workspace's `mosaico.py`; preserve credentials,
identity and user data.
