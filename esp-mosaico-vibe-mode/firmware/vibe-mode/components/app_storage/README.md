# app_storage：NAND 文件系统与访问控制

管理 SPI NAND 挂载、本地任务占用、读取缓存和事务后回收。

## 用法

```c
if (app_storage_acquire() == ESP_OK) {
    /* 同步文件 IO */
    app_storage_release();
}
```

所有路径均须释放占用并处理返回值。`app_storage_error()` 提供初始化及底层读取故障。
本地 reservation 不保护已打开的远端流；流生命周期由 Iris 管理。

## 配置

- `CONFIG_IRIS_FACTORY_NAND_CLOCK_MHZ` / `CONFIG_IRIS_FACTORY_NAND_QIO`：
  [固件默认配置](../../sdkconfig.recovery.defaults)使用 QIO 80MHz；单线板需关闭 QIO。
  本组件自行初始化 SPI3，工作频率独立于 BSP NAND API 的默认值。
- `CONFIG_IRIS_FACTORY_NAND_READ_CACHE_KIB`：默认 64KiB PSRAM，0 禁用，上限 128KiB；
  缓存分配失败回退为直接读取。写入/擦除使相关页失效，错误、ioctl 和同步清空缓存。
- `CONFIG_IRIS_FACTORY_NAND_RECLAIM`：在下载、删除、保存开发 Idea及批量更新每项成功后回收。
- `CONFIG_IRIS_FACTORY_NAND_POLL_SHORT`：使用 polling 执行页加载和 READY 短事务。
- `CONFIG_IRIS_FACTORY_IO_DIAGNOSTICS`：启用 IO/存储计时日志，默认关闭。

LittleFS lookahead 为 8192 字节，覆盖现有约 6 万个逻辑块。四线初始化先保持 WP/HOLD 为高，
以单线 20MHz 开启并核验 QE，再连接 IO2/IO3。ECC、坏块策略及磁盘格式保持不变。
逻辑擦除使用 TRIM，由 Dhara 自动 GC 管理物理回收。

## 挂载、格式化与回收

普通挂载只读探测已有卷容量，不自动格式化、扩容或迁移；失败保留数据并返回错误。

格式化仅在用户确认后执行：Ideas worker 取得本地存储和系统更新读租约，停止并排空
Iris 文件访问，调用 `app_storage_format()` 清除 FTL 映射并重建 LittleFS，最后恢复 Iris。
此操作清空 NAND，不触碰 NOR 应用、身份、Wi-Fi 或设置；不能在渲染任务中调用。

回收持有 LittleFS VFS 锁，先完成一致性处理并同步，再遍历数据、元数据及 orphans，
仅 TRIM 不可达逻辑页。任何文件或目录仍打开时跳过，维护失败不撤销已提交的 Idea。
候选位图和存活位图各约 8KiB PSRAM；分配失败不会丢弃映射。
首次扫描覆盖历史映射，可能耗时较长；扫描期间让出 CPU，但持续持有文件系统锁。

## 维护与诊断

本地 LittleFS、SPI NAND、Dhara 的版本和补丁见[第三方依赖说明](../../third_party/README.md)。
依赖通过 `override_path` 直接构建，不修改 `managed_components`。
升级或修改回收逻辑时需检查重复覆盖、重启、打开句柄和错误路径的数据完整性。
主机容量回归默认使用本地 LittleFS；`LITTLEFS_SOURCE_DIR` 可选择其他核心进行兼容验证。

`nand_perf` 统计占用窗口内整个设备的增量，可能包含并发 Iris IO。
时间字段存在嵌套，不能相加；`programs/erases` 包含 FTL 搬移，不能当作应用有效数据量。
指标定义见 [storage_metrics.c](src/storage_metrics.c)。
Idea 传输和回读使用 16KiB 缓冲，按 20ms 预算让出 CPU；同一下载任务复用 HTTPS 连接，
读空闲 20s 后进入有界重试。
