# Linux 性能测试平台

基于 Flask + 原生前端技术构建的 Linux 网络性能测试 Web 应用。采用**中心-节点**架构：本地中心服务负责管理和展示，所有 iperf3 打流、硬件监控、CPS 测试均在远程节点上执行。

## 功能特性

- **iperf3 互相打流**：支持 TCP/UDP，可配置时长、并行流数、带宽限制、反向模式、双向测试
- **实时监控**：带宽、PPS、并发连接数
- **CPS 测量**：自定义 TCP 连接建立速率测试
- **硬件监控**：远程节点的 CPU、内存、网络实时采集
- **数据持久化**：SQLite 存储所有测试记录和指标快照
- **Web 仪表盘**：实时 SSE 推送、Chart.js 可视化、测试历史回溯

## 架构

```
┌─────────────┐      HTTP REST      ┌──────────────┐
│   Center    │ ←────────────────→ │  Node Agent  │
│  (本地)      │   任务调度/结果采集   │  (远程节点)   │
│ Flask+SQLite│                    │ iperf3+psutil│
│  Web Dashboard                    │              │
└─────────────┘                    └──────────────┘
```

## 快速开始

### 1. 中心服务 (Center)

```bash
cd center
pip install -r requirements.txt
python app.py
```

访问 http://localhost:5000

### 2. 节点代理 (Agent)

在每台测试机器上：

```bash
cd agent
pip install -r requirements.txt
python agent.py
```

或一键安装为 systemd 服务：

```bash
cd agent
sudo bash ../deploy/install_agent.sh
```

> **系统依赖**：节点上必须安装 `iperf3`（`apt install iperf3` 或 `yum install iperf3`）

### 3. 使用

1. 在 Web UI 中**添加节点**（填写节点 IP 和 Agent 端口）
2. 点击**检测**确认节点在线
3. 选择**客户端节点**和**服务端节点**
4. 配置测试参数，点击**开始测试**
5. 观察实时图表和指标卡片
6. 测试完成后在**测试历史**中查看详情和下载原始 JSON

## 目录结构

```
Performance-test/
├── center/              # 中心服务
│   ├── app.py           # Flask 入口
│   ├── models.py        # SQLAlchemy 数据库模型
│   ├── services/        # 业务逻辑 (任务编排, SSE)
│   ├── routes/api.py    # REST API + SSE 端点
│   ├── utils/           # iperf3 解析、格式化工具
│   ├── static/          # CSS + JS + Chart.js
│   └── templates/       # HTML 模板
│
├── agent/               # 节点代理
│   ├── agent.py         # Flask 入口
│   ├── services/        # iperf3 执行、psutil 监控、CPS 测试
│   └── routes/agent_api.py  # Agent API
│
└── deploy/              # 部署脚本
    ├── agent.service    # systemd 服务文件
    └── install_agent.sh # 一键安装脚本
```

## 环境变量

### Center
| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CENTER_HOST` | `0.0.0.0` | 监听地址 |
| `CENTER_PORT` | `5000` | 监听端口 |
| `AGENT_POLL_INTERVAL` | `1.0` | 轮询 Agent 间隔(秒) |
| `DEBUG` | `true` | 调试模式 |

### Agent
| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AGENT_HOST` | `0.0.0.0` | 监听地址 |
| `AGENT_PORT` | `5001` | 监听端口 |
| `METRICS_INTERVAL` | `1.0` | 硬件采集间隔(秒) |
| `CPS_WORKER_THREADS` | `50` | CPS 测试并发线程数 |

## API 概览

### Center API
- `GET/POST /api/nodes` — 节点管理
- `POST /api/tests/start` — 启动测试
- `GET /api/stream/<test_id>` — SSE 实时流
- `GET /api/tests/<id>/results` — 获取 iperf3 结果
- `GET /api/tests/<id>/hardware` — 获取硬件快照

### Agent API
- `GET /agent/health` — 健康检查
- `POST /agent/iperf3/server/start` — 启动 iperf3 服务端
- `POST /agent/iperf3/client/start` — 启动 iperf3 客户端
- `POST /agent/cps/start` — 启动 CPS 测试
- `GET /agent/metrics/current` — 获取当前硬件指标
- `GET /agent/metrics/series` — 获取采集序列

## 技术栈

- **Backend**: Python 3, Flask, SQLAlchemy, requests, threading
- **Frontend**: HTML5, CSS3, Vanilla JavaScript, Chart.js (CDN)
- **Database**: SQLite
- **Hardware Metrics**: psutil
- **Network Testing**: iperf3 (system dependency)

## 注意事项

- Agent 需要 **root** 权限运行 systemd 服务，以确保 `psutil` 能正确采集网络计数器
- 节点间需保证 Agent 端口互通（默认 5001）
- iperf3 服务端端口（默认 5201）需在节点防火墙中放行
- 生产环境建议为 Center-Agent 通信启用 TLS
