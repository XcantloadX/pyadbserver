# pyadbserver

Python 实现的最小 ADB host 侧 smart-socket 服务器。M0 提供：
- `host:version`（返回文本版本号）
- `host:kill`（回复 OKAY 后优雅关闭）

本地运行（PowerShell 示例）：

```powershell
# 作为模块启动（读取 $env:ADB_SERVER_PORT 或使用 --port）
py -m pyadbserver --host 127.0.0.1 --port 5038

# 或运行仓库根的入口脚本
py -3 .\main.py

# 运行测试
uv run python -m unittest discover -s pyadbserver/tests -p 'test_*.py' -v
```

或直接运行某个测试：

```powershell
uv run python -m unittest tests.test_m0
```

### 模块与类交互示意

```mermaid
flowchart TD
    subgraph Client[ADB 客户端]
        A[Smart Socket 请求<br/><len-hex + payload>]
    end

    subgraph Server[pyadbserver]
        Srv[server/adb_server.AdbServer\nasyncio TCP 监听] --> Sess[server/session.SmartSocketSession\n解析/路由]
        Sess -->|host:*| Host[server/host_services.HostServices]
        Sess -->|设备服务（未来）| Reg[services/registry]
        Host -->|host:version/kill| Sess

        subgraph Transport
            DM[transport/device_manager.SingleDeviceManager\n固定单设备]
            Dev[transport/device.Device]
        end

        Sess -.获取/预选设备.-> DM
        DM --> Dev
    end

    A -->|TCP 连接 端口 5037 或自定义| Srv
    Host -.host:kill 触发-.-> Srv
```

