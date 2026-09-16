# ESP-Mosaico Factory Reference

`factory` 是 `esp-mosaico-recovery` 内置的 ESP-Mosaico 保留 Recovery 固件，
其源码和评审 bundle 与 `mosaico.py recover` 一同维护。普通应用从宿主
workspace 的 `projects/hello_world` 创建，不应将本工程作为应用安装到 `ota_0`。

当前源码构建的 Recovery 固件版本为 `0.1`，由
`sdkconfig.recovery.defaults` 中的 `CONFIG_APP_PROJECT_VER` 定义。
`prebuilt/recovery` 基础包也使用 `0.1`，其 manifest 记录各镜像的大小与 SHA-256。
默认 `recover` 使用该包，`recover --source current` 使用当前源码重新构建。
Recovery ABI 与分区布局由工程配置和包 manifest 约束。

System Update 版本检查将 `0.1` 解析为 `0.1.0`，只接受同一主版本线、且
最低版本要求不高于当前 Recovery 的更新包。Recovery 自更新拒绝降级或
跨主版本线的镜像。

## 静态开机 Logo

保留 Recovery 的二级 bootloader 在选择应用分区前，通过 SPI2 QSPI 初始化
CO5300，绘制黑底橙色点阵 `mosaico`。Logo 使用紧凑的字形数据逐像素生成，
不依赖 LVGL、GSP、PSRAM 或外部 UI 资源。支持 eFuse 标识的 v1.0、v1.1 和
v1.2 板；未知板型或 SPI 传输失败时跳过 Logo，继续正常启动与 Recovery。

绘制成功且发送 Display On 后，bootloader 在 LP STORE15 发布 `0x4D4C4344`
交接标记。匹配版本的 BSP 消费并清除该标记，跳过屏幕 reset、Sleep Out、亮度
重设和重复 Display On，使 Logo 保留至应用首次刷新；无标记时使用原初始化路径。
LP STORE15 因此保留给此启动交接协议，其他组件不应使用它。

bootloader 默认仅保留 ERROR 日志，以适配 `0x2000` 到 `0x8000` 的 24 KiB
固定空间。分区布局、OTA 选择、Recovery Boot 按键和恢复协议不变。维护者必须
在更新源码后重新生成并校验 `prebuilt/recovery` 的完整包，不能只替换其中一个
镜像；普通应用更新仍使用宿主 workspace 的 `mosaico.py install`。

## 用户命令

在仓库根目录运行：

```sh
python mosaico.py list
python mosaico.py recover
python mosaico.py install --project projects/<project>
python mosaico.py monitor
```

- `list` 列出仓库适配的设备型号，不查询当前连接设备。
- `recover` 初始化或恢复设备，默认使用仓库内经过评审的基础包；实时显示基础包
  校验、设备检测、ESP-IDF 构建/烧录、镜像哈希校验、重连和 Recovery 就绪验证。
- `install` 构建并通过 ESP-Iris 安装普通应用；不会自动执行 `recover`。
- `install` 默认实时显示构建、Recovery 切换、传输进度、重连和固件校验阶段；
  `--json` 模式保持稳定机器输出，详细过程仍保存在运行日志中。
- `monitor` 先显示保留日志，再持续跟随；按 `Ctrl+C` 正常结束。

Recovery 屏幕在普通 OTA 写入期间显示应用镜像接收进度、传输所有者和
SHA-256 校验状态；完成后显示重启提示。System Update 继续复用同一进度页面。

### Recovery 自更新（接受 ROM 兜底）

维护者可从当前 Recovery 构建生成只含一个 `recovery` 组件的专用包：

```sh
idf.py -C firmware/recovery build recovery-self-update-bundle
python mosaico.py system-update \
  --bundle firmware/recovery/build/factory-recovery-update.irisfw
```

制包器把 `factory.bin` 以 `0xff` 补齐至整个 1.75 MiB `factory` 槽。分区表不作为
组件进入包；制包时只把它的 SHA-256 写入顶层 `target_layout_sha256`，作为明确的
设备布局前置条件。设备先确认当前分区表哈希满足该条件，再在 PSRAM 中分配连续的
完整槽位、接收并校验 SHA-256 和 ESP32-S31 镜像。只有全部预检通过后，才会临时
关闭 dangerous write protection，原地擦写 `factory`，恢复保护，再执行整槽读回
SHA-256 和 `esp_image_verify()`。成功后将下一次启动明确指向 `factory`，保存
operation receipt，并延迟重启；Gateway 必须观察到相同 Device ID、新 Boot ID、
`recovery` mode、目标 project/ELF SHA-256 和 HEALTHY 才报告成功。

该路径不改 bootloader 或 Flash 布局，也不与 normal application/data 更新混包。
它仍是单副本原地更新：从开始擦除到完成校验之间掉电，可能导致 Recovery 无法启动，
此时需按仓库规定进入 ROM download mode；开发期间运行
`python mosaico.py recover --source current` 恢复本分支构建，发布后则使用已评审的
Recovery 包。不具备自更新能力的设备必须走 ROM/`recover` 路径。

### Recovery HTTPS Bridge

Recovery 主动通过 HTTPS 连接 Bridge 服务，支持 `partitions`、`layout` 和
`factory`。本仓库的 Recovery 源码构建默认连接
`https://iris-bridge.esp-claw.com`，并使用 `esp-mosaico` board ID。部署到其他
环境时，通过 `CONFIG_IRIS_FACTORY_BRIDGE_SERVER_URL`（无末尾斜杠的 HTTPS
Origin）和 `CONFIG_IRIS_FACTORY_BRIDGE_BOARD_ID` 覆盖这两个值；任一值为空都不注册。

用户进入 **Bridge download** 页面后，设备等待 Wi-Fi IP、注册并显示服务器
配对码。网页配对并上传后，设备拉取任务、验证并写入；一次会话仅烧录一次。
退出会请求异步安全停止，完成或失败后重新进入页面才能再次配对。

```sh
python mosaico.py recovery-wifi --ssid SSID
python mosaico.py bridge-code --device-id DEVICE_ID --timeout 60
```

USB 命令打开同一个页面并等待配对码；重复打开不换码。控制服务 `0x1202` 的
方法 4 打开，方法 5 只查询状态，旧方法 3 已移除。服务地址、板型缺失时提示
重新配置构建。两个方法均拒绝 TCP，不返回或记录设备 token。

设备端实现位于 [iris_bridge 组件](components/iris_bridge/)。
旧本地 HTTP server、URL 下载 RPC、`http-update-code` 和 `--manifest-url`
已移除，USB bundle 和 NAND 更新继续使用共享写入后端。

### Recovery 从 NAND LittleFS 读取系统更新

ESP-Mosaico 的板载 NAND 与 `esp-mosaico-claw` 一致，使用 SPI NAND、wear-leveling
block device 和 LittleFS，挂载点为 `/nand`。Recovery 读写挂载已有文件系统，并将
整个挂载点注册为 ESP-Iris 文件卷 `nand`；可通过 Gateway 列目录、读取、写入、删除、
建目录和重命名。写入先落到同目录临时文件，校验 SHA-256 后再原子替换目标文件。
挂载失败时不会格式化 NAND，也不会阻止 Recovery USB 维护服务启动。将解包后的
bundle 放到同一目录，例如：

```text
/nand/system-update/manifest.json
/nand/system-update/ota_0.bin
/nand/system-update/bootloader.bin
/nand/system-update/partition-table.bin
```

Recovery 首页提供 **Update from NAND**：进入后固件会异步扫描以下两种
catalog 布局，最多列出 8 个完整 bundle；点击条目可先核对 release、组件数、总
容量和 manifest 路径，再确认更新。

```text
/nand/system-update/manifest.json
/nand/system-update/<release>/manifest.json
```

每个 `manifest.json` 引用的组件必须与它位于同一目录。扫描阶段会过滤 manifest
格式错误、组件缺失或文件大小不符的条目；确认安装后，System Update backend
仍会重新执行完整 manifest、SHA-256、镜像和布局校验。也可以通过产品 CLI 直接
启动指定路径：

```sh
python mosaico.py system-update --device-id DEVICE_ID \
  --manifest-path /nand/system-update/manifest.json
```

Recovery 逐块读取组件并复用与 USB、Bridge 相同的 manifest、SHA-256、镜像及
分区布局校验。v1 manifest 必须将 partition table 放在首个组件；Recovery 验证
当前表和目标表中的五个不可变分区后，按照目标表流式写入 application 和 data。
bootloader 暂存到 PSRAM，全部验证完成后统一提交。三种来源共用一个 Flash writer owner，不能
并行执行。可通过 `CONFIG_IRIS_FACTORY_NAND_SYSTEM_UPDATE_AUTO_START=y` 配置固定
路径自动启动；默认关闭，避免误用 NAND 中遗留的旧 bundle。启动 NAND 更新后不要
再通过文件服务修改该 bundle；单文件上传是原子的，但一个 bundle 的多个文件不构成
同一事务。

## Flash 布局

16 MiB Flash 使用固定系统前缀和尾部可缩减的单应用槽：

| 分区 | Offset | Size | 用途 |
| --- | ---: | ---: | --- |
| `otadata` | `0x9000` | 8 KiB | ESP-IDF OTA 选择与回滚状态 |
| `phy_init` | `0xb000` | 4 KiB | PHY 初始化数据 |
| `sysmeta` | `0xc000` | 80 KiB | 系统专用 NVS |
| `factory` | `0x20000` | 1.75 MiB | 保留 Recovery |
| `coredump` | `0x1e0000` | 128 KiB | 崩溃证据预留空间 |
| `nvs` | `0x200000` | 64 KiB | 应用 NVS |
| `ota_0` | `0x210000` | 13.94 MiB | 普通应用；后续布局可从尾部缩减 |

固定系统前缀从 Flash 起始到 `coredump` 结束恰好为 2 MiB，
`nvs` 和普通应用从 `0x200000` 之后开始。

`sysmeta` 中的 `esp_iris`、`wifi`、`iris_ota_demo` 和 `update` namespace
分别保存 TCP pairing token、Factory Wi-Fi、Recovery OTA 状态和
最后一次系统更新结果。System Update v1 只要求 `otadata`、`phy_init`、
`sysmeta`、`factory` 和 `coredump` 的名称、类型、子类型、offset、size 与 flags
严格符合上表；`nvs`、`ota_0` 以及其他应用数据分区可由目标表调整。

常用选项可通过 `python mosaico.py <command> --help` 查看。自动化环境可加
`--json`；`recover` 在唯一识别到受支持设备后直接执行，无需二次确认。

## 工程维护者

普通用户不应直接调用底层构建或写入命令。Recovery 基础包和内部写入 target
由 `mosaico.py recover` 管理；普通应用始终由 `mosaico.py install` 通过
ESP-Iris 安装。评审包包含完整哈希与布局约束，只有通过构建校验和真机验收后
才应发布。

Recovery 工程直接使用 workspace 中的 `ESP-Iris`。BSP 依赖由组件
manifest 指向 `https://github.com/esp-mosaico/esp-mosaico-bsp`；集成到
ESP-Mosaico workspace 时，`mosaico.py recover` 会根据宿主 workspace 的
`.mosaico.json` 注入本地 `esp-mosaico-bsp`，并复用 workspace 中的 ESP-Iris，
保证 Recovery、设备工具与普通应用使用同一 Iris 版本。
