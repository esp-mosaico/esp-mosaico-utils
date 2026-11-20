# ESP-Mosaico component boundaries

ESP-Mosaico Utils provides reusable device, host and application-integration
components. A consuming workspace owns its applications, board support package
(BSP) pins, `.mosaico.json` and product-specific configuration.

| Owner | Responsibilities | Public entry points |
| --- | --- | --- |
| ESP-Iris | Device protocol and component, host Gateway and Web Workbench | [Component guide](../ESP-Iris/components/esp_iris/README.md), [architecture](../ESP-Iris/docs/esp-iris-architecture.md), [Gateway guide](../ESP-Iris/components/esp_iris/tools/README.md) |
| Mosaico Tools | Workspace CLI, templates, application adapter and Recovery integration | [Application integration](../mosaico-tools/docs/application-integration.md), [migration guide](../mosaico-tools/docs/migration-0.2.md) |
| Shared resources | Consumer-independent GSP acquisition and Ideas display-resource generation | [Shared resources](../shared/README.md) |
| Reviewed Recovery bundle | CI-generated Vibe Mode firmware bundle used by Recovery operations | [Recovery migration](recovery-iris-migration.md), [bundle manifest](../firmware/recovery/manifest.json) |
| Consuming workspace | Applications, BSP selection and product configuration | [Application integration](../mosaico-tools/docs/application-integration.md) |

Mosaico Tools uses ESP-Iris public host APIs and the public Recovery contract.
Vibe Mode implements that contract; ordinary applications integrate through
the documented adapter and do not own the retained maintenance firmware.
