# PyADB Server 协议文档

## Host 命令

### host:tport:*

**Connection**: KEEP-ALIVE

选择传输设备的命令。

---

## 设备服务命令


### shell:\<cmd\> - 非交互式命令执行

**语法**：`shell:<command>`

**连接**：CLOSE

**特性**:
- 执行单个命令后立即返回
- stdout和stderr合并输出
- 不返回退出码
- 兼容旧版adb客户端

**流程**:
```
>>> <length>shell:echo hello
<<< OKAY
<<< <command output>
TCP:CLOSE
```

### shell：- 交互式Shell

**语法**：`shell:`

**连接**：KEEP-ALIVE

**特性**:
- 启动交互式shell会话
- 支持stdin/stdout双向通信
- stdout和stderr合并
- 不返回退出码

**流程**:
```
>>> 0005shell:
<<< OKAY
<<< [inital shell prompt]
>>> [stdin data]
<<< [stdout data]
>>> [stdin data]
<<< [stdout data]
>>> [stdin data]
// ...
```

### shell,v2: / shell,v2:\<cmd\>

Shell Protocol v2 - 支持分离stderr和退出码的现代shell协议。

#### Shell Protocol v2 包格式

每个数据包的格式:
```
+--------+----------------+--------------+
| ID (1) | Length (4)     | Data (N)     |
| byte   | little-endian  | bytes        |
+--------+----------------+--------------+
```

**包类型 (ID)**:
- `0` (STDIN): 客户端输入数据
- `1` (STDOUT): 标准输出数据
- `2` (STDERR): 标准错误数据  
- `3` (EXIT): 退出码 (1字节数据)
- `4` (CLOSE_STDIN): 关闭stdin信号
- `5` (WINDOW_SIZE_CHANGE): 窗口大小变化 (需要PTY)

**编码示例** (Python):
```python
import struct

def encode_packet(packet_id: int, data: bytes) -> bytes:
    length = len(data)
    header = struct.pack("<BI", packet_id, length)
    return header + data

# STDOUT包
stdout_packet = encode_packet(1, b"Hello World")
# 结果: 01 0b 00 00 00 48 65 6c 6c 6f 20 57 6f 72 6c 64

# EXIT包 (退出码=0)
exit_packet = encode_packet(3, b"\x00")
# 结果: 03 01 00 00 00 00
```

#### shell,v2:\<cmd\> - 非交互式命令执行

**语法**: `shell,v2:<command>`

**Connection**: CLOSE

**特性**:
- 分离stdout和stderr
- 返回准确的退出码
- 支持stderr独立流

**流程**:
```
Client -> Server: <length>shell,v2:echo hello
Server -> Client: OKAY
Server -> Client: [ID=1][Len=6][hello\n]     # STDOUT包
Server -> Client: [ID=3][Len=1][0]           # EXIT包 (退出码=0)
[连接关闭]
```

**完整示例** (包含stderr):
```
命令: shell,v2:echo hello; echo error >&2

响应:
- OKAY
- [01][06 00 00 00][hello\n]              # STDOUT
- [02][06 00 00 00][error\n]              # STDERR  
- [03][01 00 00 00][00]                   # EXIT (0)
```

#### shell,v2: - 交互式Shell

**语法**: `shell,v2:`

**Connection**: BIDIRECTIONAL

**特性**:
- 双向protocol包通信
- 分离stdout/stderr
- 返回退出码
- 支持CLOSE_STDIN信号
- 支持窗口大小变化

**流程**:
```
Client -> Server: 0009shell,v2:
Server -> Client: OKAY
[protocol包双向通信]
Client -> Server: [ID=0][Len=5][ls -l]       # STDIN
Server -> Client: [ID=1][Len=...][...]       # STDOUT
Client -> Server: [ID=4][Len=0][]            # CLOSE_STDIN
Server -> Client: [ID=3][Len=1][0]           # EXIT
[连接关闭]
```

---

### exec: / exec:\<cmd\>

Exec服务 - 类似shell但传统上使用raw PTY模式。

#### exec:\<cmd\> - 非交互式执行

**语法**: `exec:<command>`

**Connection**: CLOSE

**特性**:
- 原始模式执行 (不进行输出处理)
- 合并stdout/stderr
- 不返回退出码

**用途**: 
- 需要原始输出的命令
- 避免终端控制字符干扰

#### exec: - 交互式Exec

**语法**: `exec:`

**Connection**: BIDIRECTIONAL

**特性**:
- 使用PTY模式 (如果支持)
- 适合需要终端特性的程序

---

## 四种Shell模式对照表

根据ADB官方实现，shell服务支持四种组合：

| 模式 | 协议 | 退出码 | 分离stderr | 用途 | 实现状态 |
|------|------|--------|-----------|------|----------|
| PTY + 无协议 | 否 | 否 | 否 | 传统交互式shell | 部分支持 |
| Raw + 无协议 | 否 | 否 | 否 | 简单命令执行 | ✅ 完全支持 |
| PTY + 协议 | 是 | 是 | 否* | 现代交互式shell | 部分支持 |
| Raw + 协议 | 是 | 是 | 是 | 现代命令执行 | ✅ 完全支持 |

\* PTY模式下stdout和stderr通常合并，但退出码仍然通过协议返回

---

## 实现细节

### 子进程管理

**Windows平台**:
- 使用 `cmd.exe` 或 `powershell.exe`
- PTY支持有限 (可使用ConPTY在Windows 10+)
- 推荐使用raw模式

**Unix/Linux/macOS平台**:
- 使用 `/bin/sh` 或 `$SHELL` 环境变量
- 完整PTY支持 (通过`pty.openpty()`)
- 支持所有模式

### 数据流处理策略

#### 非交互式 + Protocol模式
1. 创建子进程，重定向stdout和stderr到PIPE
2. 并行读取两个流
3. 将数据封装为对应ID的protocol包发送
4. 进程退出后发送EXIT包

#### 交互式 + Protocol模式
1. 从客户端读取protocol包
2. 根据ID处理:
   - STDIN → 写入子进程stdin
   - CLOSE_STDIN → 关闭子进程stdin
   - WINDOW_SIZE_CHANGE → 调整PTY窗口大小
3. 从子进程读取输出并封装为STDOUT/STDERR包
4. 进程退出后发送EXIT包

#### Raw模式 (无Protocol)
1. 直接转发原始字节流
2. 合并所有输出
3. 连接关闭时子进程也终止

### 缓冲与性能

- **读取缓冲**: 4KB块大小
- **写入策略**: 每个包后立即flush
- **背压处理**: 使用asyncio的drain()机制

---

## 使用示例

### Python客户端示例

```python
import socket
import struct

def send_shell_command(host, port, cmd):
    """发送shell命令并接收输出"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    
    # 发送命令
    payload = f"shell:{cmd}"
    request = f"{len(payload):04x}{payload}".encode()
    sock.sendall(request)
    
    # 接收OKAY
    response = sock.recv(4)
    if response != b"OKAY":
        raise Exception(f"Server returned: {response}")
    
    # 接收输出
    output = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        output += chunk
    
    sock.close()
    return output

# 使用示例
result = send_shell_command("localhost", 5037, "echo hello")
print(result.decode())
```

### Shell Protocol v2客户端示例

```python
def send_shell_v2_command(host, port, cmd):
    """发送shell,v2命令并解析protocol包"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    
    # 发送命令
    payload = f"shell,v2:{cmd}"
    request = f"{len(payload):04x}{payload}".encode()
    sock.sendall(request)
    
    # 接收OKAY
    if sock.recv(4) != b"OKAY":
        raise Exception("Command rejected")
    
    stdout_data = b""
    stderr_data = b""
    exit_code = None
    
    # 解析protocol包
    while True:
        # 读取包头 (5字节)
        header = sock.recv(5)
        if len(header) < 5:
            break
        
        packet_id, length = struct.unpack("<BI", header)
        
        # 读取数据
        data = b""
        if length > 0:
            data = sock.recv(length)
        
        if packet_id == 1:  # STDOUT
            stdout_data += data
        elif packet_id == 2:  # STDERR
            stderr_data += data
        elif packet_id == 3:  # EXIT
            exit_code = data[0] if data else 0
            break
    
    sock.close()
    return exit_code, stdout_data, stderr_data

# 使用示例
code, stdout, stderr = send_shell_v2_command("localhost", 5037, "echo hello")
print(f"Exit Code: {code}")
print(f"Stdout: {stdout.decode()}")
print(f"Stderr: {stderr.decode()}")
```

### 交互式Shell示例

```python
import asyncio

async def interactive_shell(host, port):
    """交互式shell会话"""
    reader, writer = await asyncio.open_connection(host, port)
    
    # 发送shell:命令
    request = b"0005shell:"
    writer.write(request)
    await writer.drain()
    
    # 接收OKAY
    okay = await reader.readexactly(4)
    if okay != b"OKAY":
        raise Exception("Shell rejected")
    
    async def send_input():
        """从stdin读取并发送到server"""
        loop = asyncio.get_event_loop()
        while True:
            line = await loop.run_in_executor(None, input, "")
            writer.write((line + "\n").encode())
            await writer.drain()
    
    async def receive_output():
        """从server接收并打印到stdout"""
        while True:
            data = await reader.read(4096)
            if not data:
                break
            print(data.decode(), end="", flush=True)
    
    # 并行处理输入输出
    await asyncio.gather(send_input(), receive_output())

# 运行
asyncio.run(interactive_shell("localhost", 5037))
```

---

## 错误处理

### 常见错误

**FAIL: unsupported operation**
- 原因: 命令格式不正确或服务未注册
- 解决: 检查命令语法

**FAIL: command execution failed**
- 原因: 子进程创建失败或命令不存在
- 解决: 检查命令路径和权限

**连接意外关闭**
- 原因: 子进程崩溃或server内部错误
- 解决: 查看server日志

### 超时处理

建议客户端设置合理的超时:
- 命令执行: 30-60秒
- 交互式会话: 无超时或长超时 (5分钟+)

---

## 安全考虑

1. **命令注入防护**: 当前实现直接执行命令，生产环境需要:
   - 命令白名单
   - 参数验证和转义
   - 沙盒执行环境

2. **资源限制**:
   - 进程数量限制
   - 内存使用限制
   - CPU时间限制

3. **访问控制**:
   - 仅监听localhost (127.0.0.1)
   - 可选: token认证
   - 可选: TLS加密

---

## 参考资料

- [ADB Protocol 官方文档](https://android.googlesource.com/platform/system/core/+/refs/heads/master/adb/protocol.txt)
- [ADB Services 官方文档](https://android.googlesource.com/platform/system/core/+/refs/heads/master/adb/SERVICES.TXT)
- [Shell Protocol 头文件](https://android.googlesource.com/platform/system/core/+/refs/heads/master/adb/shell_protocol.h)
- [Shell Service 实现](https://android.googlesource.com/platform/system/core/+/refs/heads/master/adb/daemon/shell_service.cpp)
