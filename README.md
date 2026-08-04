# Linux 性能测试平台

基于 Flask + 原生前端技术构建的 Linux 网络性能测试 Web 应用。采用**中心-节点**架构：本地中心服务负责管理和展示，所有 iperf3 打流、硬件监控、CPS 测试均在远程节点上执行。

> **给 Claude Code 的入口**：[CLAUDE.md](CLAUDE.md) — 改代码前先读 [docs/kb/](docs/kb/) 本地知识库。

在线体验地址：[http://106.75.233.49:5002/](http://106.75.233.49:5002/)

## 功能特性

四项核心指标（定义见 [docs/性能指标.txt](docs/性能指标.txt)）：
- **BPS（带宽）** — iperf3 打流，TCP/UDP，可配置时长、并行流数、带宽限制、反向模式、双向测试
- **PPS（包每秒）** — 从网卡驱动层统计采集（ethtool → sysfs → psutil 三层回退，参考 AWS/阿里云 SR-IOV PMD 思路绕过内核）
- **CPS（连接每秒）** — 自定义 50 线程 TCP 建连测试
- **并发连接数** — 当前以 CPS 成功建连数近似（dperf 未装时的权宜方案）
- **硬件监控** — 远程节点 CPU、内存、网络实时采集（每秒）
- **数据持久化** — SQLite 存储所有测试记录和指标快照
- **Web 仪表盘** — 实时 SSE 推送、Chart.js 可视化、测试历史回溯

## 架构

```
┌─────────────┐      HTTP REST      ┌──────────────┐
│   Center    │ ←────────────────→ │  Node Agent  │
│  (本地)      │   任务调度/结果采集   │  (远程节点)   │
│ Flask+SQLite│                    │ iperf3+psutil│
│  Web Dashboard                    │ +ethtool     │
└─────────────┘                    └──────────────┘
```

Center 主动调 Agent（Agent 不回调 Center，避免入站防火墙问题）。实时指标靠 Center 每 3s 轮询两边 `/agent/metrics/current` → SSE 推前端。

## 快速开始

### 1. 中心服务 (Center)

```bash
cd center
pip install -r requirements.txt
python app.py          # 监听 0.0.0.0:5002
```

访问 http://localhost:5002。DEBUG=True 自动热重载。

### 2. 节点代理 (Agent)

在每台测试机器上（需 root）：

```bash
cd agent
sudo bash deploy/install_agent.sh    # 装 python3/iperf3/ethtool/psutil + cp 到 /opt + systemd
```

或手动：

```bash
cd agent
pip install -r requirements.txt
python agent.py        # 监听 0.0.0.0:5002
```

> **系统依赖**：节点上必须安装 `iperf3` 和 `ethtool`（脚本会自动装）。
> **dperf**：默认不装（`DPERF_INSTALL=auto` 检测到无编译环境会跳过）。dperf 未装时 PPS/CPS/并发用 iperf3+Python 方案近似。

### 3. 使用

1. 在 Web UI 中**添加节点**（填写节点 EIP 和 Agent 端口 5002）
2. 点击**检测**确认节点在线
3. 选择**客户端节点**和**服务端节点**
4. 配置测试参数（协议、时长、流数、带宽限制、是否测 CPS）
5. 点击**开始测试**，观察实时图表和指标卡片
6. 测试完成后在**测试历史**中查看详情和下载原始 JSON

> 打流目标自动用节点内网 IP（从 `/agent/health` 的 `internal_ips` 取），避免外网 EIP 带宽限制。

## 目录结构

```
Performance-test/
├── CLAUDE.md            # Claude Code 入口（指向 docs/kb 知识库）
├── README.md
├── docs/
│   ├── 性能指标.txt      # 四项核心指标定义
│   └── kb/              # 本地知识库（gitignore，防上下文丢失）
│       ├── README.md    # 索引
│       ├── architecture.md
│       ├── metrics-pipeline.md
│       ├── deployment.md
│       ├── known-issues.md
│       ├── user-workflow.md
│       └── session-log.md
├── center/              # 中心服务
│   ├── app.py           # Flask 入口
│   ├── config.py        # 配置（gitignore，本地）
│   ├── models.py        # SQLAlchemy 模型
│   ├── services/        # task_orchestrator, sse_manager
│   ├── routes/api.py    # REST API + SSE 端点
│   ├── utils/           # iperf3_parser, formatters
│   ├── static/          # CSS + JS(api/charts/app) + Chart.js CDN
│   └── templates/       # index.html
│
└── agent/               # 节点代理
    ├── agent.py         # Flask 入口
    ├── config.py        # 配置（gitignore，本地）
    ├── services/        # iperf3_runner, cps_tester, metrics_collector, dperf_runner, task_manager
    ├── routes/agent_api.py
    └── deploy/
        ├── agent.service     # systemd unit
        └── install_agent.sh  # 一键安装
```

## 环境变量

### Center（center/config.py）
| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CENTER_HOST` | `0.0.0.0` | 监听地址 |
| `CENTER_PORT` | `5002` | 监听端口 |
| `AGENT_POLL_INTERVAL` | `1.0` | 轮询间隔(秒，实际 _poll_progress 用 3s) |
| `AGENT_CONNECT_TIMEOUT` | `10` | agent 连接超时 |
| `AGENT_HEALTH_TIMEOUT` | `10` | agent 健康检查超时 |
| `DEBUG` | `true` | 调试模式（热重载） |

### Agent（agent/config.py）
| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AGENT_HOST` | `0.0.0.0` | 监听地址 |
| `AGENT_PORT` | `5002` | 监听端口 |
| `METRICS_INTERVAL` | `1.0` | 硬件采集间隔(秒) |
| `METRICS_MAX_SNAPSHOTS` | `300` | 内存快照上限 |
| `CPS_CONNECTION_TIMEOUT` | `2.0` | 单次 CPS 建连超时 |
| `CPS_WORKER_THREADS` | `50` | CPS 并发线程数 |

## API 概览

### Center API
- `GET/POST /api/nodes`、`DELETE /api/nodes/<id>` — 节点管理
- `GET /api/nodes/<id>/health` — 检测节点
- `GET /api/tests` — 测试历史（聚合 BPS/PPS/CPS/并发）
- `POST /api/tests/start` — 启动测试
- `GET /api/tests/<id>/results` — 结果（含 `pps_summary`/`cps_summary`）
- `GET /api/tests/<id>/cps` — CPS 结果
- `GET /api/tests/<id>/hardware` — 硬件快照序列
- `GET /api/stream/<test_id>` — SSE 实时流

### Agent API
- `GET /agent/health` — 健康（含 `internal_ips`、`engines`）
- `POST /agent/iperf3/server/start|stop` — iperf3 server
- `POST /agent/iperf3/client/start`、`GET /agent/iperf3/client/result` — iperf3 client
- `POST /agent/cps/start` — CPS 测试（同步阻塞返回结果）
- `POST /agent/metrics/start|stop`、`GET /agent/metrics/current|series` — 硬件采集
- `GET /agent/engines` — 引擎可用性（iperf3=True, dperf=检测）

## 技术栈

- **Backend**: Python 3, Flask, SQLAlchemy, requests, threading
- **Frontend**: HTML5, CSS3, Vanilla JavaScript, Chart.js (CDN)
- **Database**: SQLite
- **Hardware Metrics**: psutil + ethtool + sysfs（SR-IOV 三层回退）
- **Network Testing**: iperf3（系统依赖），dperf（可选，未装）

## 注意事项

- Agent 需要 **root** 权限运行 systemd 服务，以确保 `ethtool -S` 和 `psutil` 网络计数器采集正常。
- 节点间需保证 Agent 端口互通（默认 5002）。
- iperf3 服务端端口（默认 5201）需在节点防火墙中放行。
- 节点注册用 EIP，但打流 target 自动用内网 IP（避免 EIP 1M 带宽限制）。
- `config.py` 和 `perftest.db` 在 `.gitignore` 里，是本地文件。
- 生产环境建议为 Center-Agent 通信启用 TLS。
