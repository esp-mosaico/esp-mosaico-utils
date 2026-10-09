# Migrating from ESP-Iris 0.1 to 0.2

0.2 is a breaking release. Firmware, Gateway, CLI and Web clients must move
together. There is no 0.1 negotiation, parser, API alias or database conversion.
The [archived 0.1 contract](archive/0.1/spec.md) is reference documentation only.

1. Preserve any required 0.1 logs and artifacts externally, stop its Gateway,
   and install/build the matching 0.2 firmware and host checkout. Use the
   product's documented native installation/recovery procedure for the first
   transition; a 0.2 Gateway cannot update a 0.1 device over Iris.
2. Keep the standard ESP-IDF console enabled. UART uses its existing IDF baud
   rate. USB Serial/JTAG retains native reset and JTAG. A product REPL must
   register the Iris command and size its receive queue as described in
   `esp_iris_console.h`; otherwise Iris owns the console command reader.
3. For application USB enable two CDC interfaces. CDC0 is text/control and
   CDC1 is data. TCP exposes two distinct ports. Discover roles through USB
   descriptors or mDNS/HELLO, then verify the device/boot/owner binding during
   each link handshake. Do not pair interfaces by port adjacency or IP alone.
4. UART and Serial/JTAG support control, jobs, input and bounded screenshots.
   Continuous media, files and firmware require data. Use screenshot
   `path=auto|control|data`; `auto` prefers data and falls back to control.
5. Change HTTP/WebSocket clients to `/v2` and require Gateway API major 2.
   Media credits and stop requests carry the negotiated stream ID. Use fresh
   0.2 state directories; the new schema refuses old databases without modifying
   them. Default host storage is isolated under `esp-iris/0.2`.
6. Close stock monitor before starting Gateway on that endpoint, and release
   Gateway before opening monitor or flashing. No firmware mode switch is
   required. Hardware reset is an explicit action; reconnect does not reset.

Rebuild System Update archives using the `esp-iris-system-update/0.2` manifest.
Old `/v1` and historical `/v2` manifests are rejected; changing a schema string
is not a migration.

Partition layout, retained firmware, boot policy, native flash bundles and
application update selection belong to the product, not the Iris component.
