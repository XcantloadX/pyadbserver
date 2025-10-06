# SYNC

本文档描述 Android ADB 文件同步协议的 v1 版本。

- 首次请求：客户端通过 smart-socket 发送 `sync:`，服务端返回 `OKAY` 后进入二进制同步模式。
- 同步模式：所有整数使用 little-endian，消息以 8 字节头开始：`[4字节ASCII ID][4字节uint32 长度]`。
- 连接生命周期：在同一 TCP 连接上循环处理请求，直至接收到 `QUIT` 或连接关闭。

## 支持的请求与响应（v1）

- **LIST**: 列目录
- **STAT**: Stat 文件/目录
- **RECV**: 读取文件（设备→主机）
- **SEND**: 写入文件（主机→设备）
- **QUIT**: 退出同步模式

此外使用的帧类型：
- **DENT**: 目录项
- **DATA**: 数据分块（最大 64KiB）
- **DONE**: 操作结束（在 SEND 中，length 携带 mtime）
- **OKAY**: 成功确认（SEND 完成后返回）
- **FAIL**: 失败，以及可选的错误消息（紧随其后的 `length` 字节）

ID 常量（4 字节 ASCII）：`LIST`, `STAT`, `RECV`, `SEND`, `DENT`, `DATA`, `DONE`, `OKAY`, `FAIL`, `QUIT`

所有 `path` 均按 UTF-8 编码，长度为前置的 `length` 字段指定的字节数（无 NUL 终止）。

## 帧格式

通用头：
```
+--------+----------------+
| ID(4)  | Length (4)     |
| ascii  | uint32 le      |
+--------+----------------+
```
紧随其后为 `Length` 字节的负载（若有）。

### LIST
- 请求：`LIST` + `length` + `path`（utf-8）
- 响应：重复 0..N 次 `DENT`，最后 `DONE(0)`

DENT 载荷（v1）：
```
<4s id='DENT'><uint32 mode><uint32 size><uint32 mtime><uint32 namelen><name bytes>
```

### STAT
- 请求：`STAT` + `length` + `path`
- 响应（v1）：
```
<4s id='STAT'><uint32 mode><uint32 size><uint32 mtime>
```

### RECV（读文件）
- 请求：`RECV` + `length` + `path`
- 响应：若干 `DATA` 分块 + `DONE(0)` 结束

DATA 分块：
```
<4s id='DATA'><uint32 size><size bytes of data>
```

### SEND（写文件）
- 请求第一帧：`SEND` + `length` + `spec`
  - `spec` 文本为 `"<path>,<mode>"`，其中 `<mode>` 为十进制权限（如 `33206`）。
- 随后客户端发送若干数据帧：
  - 0..N 次 `DATA` 分块
  - 1 次 `DONE(mtime)` 作为收尾（`mtime` 为 4 字节 uint32 时间戳）
- 响应：`OKAY(0)` 表示成功；失败返回 `FAIL(len)+message`

### QUIT
- 请求：`QUIT(0)`
- 响应：无；服务端退出同步模式并关闭连接。

## 错误处理
- 对未知 ID：返回 `FAIL("unknown sync id")` 并结束会话。
- 对解析错误或 I/O 错误：返回 `FAIL(<message>)` 并结束当前操作；严重错误将结束会话。
- 路径长度建议 ≤1024（与上游实现一致），超限可直接 `FAIL`。

## 文件系统抽象（AFS）
`SyncService` 通过 `AbstractFileSystem` 访问存储，默认实现为 `LocalFileSystem`：
- 默认根目录：当前工作目录（不沙盒化）。
- 接口：
  - `stat(path) -> FileStat(mode,int size,int mtime)`
  - `iterdir(path) -> Iterable[Dirent(name,mode,size,mtime)]`
  - `open_for_read(path) -> BinaryIO`
  - `open_for_write(path, mode:int) -> BinaryIO`
  - `set_mtime(path, mtime:int)`
  - `makedirs(path)`

实现方可以自定义后端并在 `SyncService(fs=...)` 注入使用。

## 兼容性
- 本实现覆盖 v1 的基本操作；暂未实现 v2（`STAT2`/`LIST2` 等）与压缩标志（brotli/lz4/zstd）。
- 数据块最大 64KiB。
- Windows 平台的 `mode` 语义不同，设置权限尽力而为；`mtime` 使用 `os.utime`。

## 参考
- `adb/docs/sync.md`
- `adb/file_sync_protocol.h`
- ADB 源码中的 `services.cpp` 与同步服务实现

