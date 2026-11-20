# main: device composition root

Initializes platform services, starts Recovery, reads shared Wi-Fi configuration,
loads the UI bundle, prepares the display, starts GSP and attaches the application
controller, in that order. It contains no input handling, animation or drawing
rules and exports no headers.

Private dependencies: `app_config`, `app_display`, `app_hello`, Iris, Recovery,
bundle loading, screen mirroring, Mbed TLS, NVS and logging. Shared product/platform
components retain their names. Central dependency pins/overrides live in
`idf_component.yml`.

ESP-IDF invokes `app_main()` once in task context; it takes no parameters and
returns after startup. Its private composition context retains only owned opaque
handles; UI/controller lifetime extends until reboot. The shared configuration
example logs availability only, clears its temporary credential snapshot, and
continues UI startup on missing or invalid configuration. It does not start Wi-Fi.
See [`app_config`](../components/app_config/README.md) for the read contract.
Bundle or display initialization failure leaves Recovery reachable;
other unrecoverable initialization errors use ESP-IDF's error-check policy.
Build/run the project through the workspace launcher described in the root README.
