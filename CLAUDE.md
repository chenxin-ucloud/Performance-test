# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 本地知识库（优先读取）

**在动手改任何代码之前，先读 [docs/kb/](docs/kb/) 下的记录**——这是为防止上下文丢失而维护的项目级知识库，记录了架构深析、指标数据流、部署细节、历史 bug 与修复、用户工作方式。`docs/` 在 `.gitignore` 里，知识库为本地文件，不进 git。

- [docs/kb/README.md](docs/kb/README.md) — 知识库索引与阅读顺序
- [docs/kb/architecture.md](docs/kb/architecture.md) — Center-Node 架构深析
- [docs/kb/metrics-pipeline.md](docs/kb/metrics-pipeline.md) — BPS/PPS/CPS/并发 数据流（agent→DB→API→UI）
- [docs/kb/deployment.md](docs/kb/deployment.md) — 远程节点、部署路径、systemd、SSH 凭据
- [docs/kb/known-issues.md](docs/kb/known-issues.md) — 历史 bug 与修复（含本轮 CPS/PPS 修复）
- [docs/kb/user-workflow.md](docs/kb/user-workflow.md) — 用户工作方式与反馈约定（必读）
- [docs/kb/session-log.md](docs/kb/session-log.md) — 每轮会话摘要

**改完代码后必须同步更新**知识库（affected 章节）和 [README.md](README.md)（若行为/端口/路径变化）。这是硬性要求，不是可选。

## 项目本质

Flask 中心 + Flask 轻量 agent 的 Linux 网络性能测试平台。**关键约束：本地 center 只做管理和展示，所有打流（iperf3）、CPS、硬件监控都在远程节点 agent 上执行。** 四项核心指标定义见 [docs/性能指标.txt](docs/性能指标.txt)（BPS/PPS/CPS/最大并发连接数）。

## 常用命令

```bash
# 启动 center（本地，DEBUG=True 会自动热重载）
cd center && python app.py            # 监听 0.0.0.0:5002

# 语法检查（无测试框架，改完必跑）
cd center && python3 -m py_compile routes/api.py services/task_orchestrator.py models.py
cd agent  && python3 -m py_compile routes/agent_api.py services/cps_tester.py services/metrics_collector.py
node -e "new Function(require('fs').readFileSync('center/static/js/app.js','utf8'))"   # JS 语法检查

# 查数据库（表结构变了要删库重建：rm center/perftest.db，app.py 启动时 db.create_all()）
sqlite3 center/perftest.db ".tables"
sqlite3 -header -column center/perftest.db "SELECT id,status,measure_cps FROM test_runs ORDER BY id DESC LIMIT 5;"
sqlite3 -header -column center/perftest.db "SELECT * FROM cps_results WHERE test_id=<id>;"
sqlite3 -header -column center/perftest.db "SELECT test_id,node_id,COUNT(*) FROM hardware_snapshots GROUP BY test_id,node_id;"

# 部署 agent 到远程节点（agent 不热重载，改了 agent 必须 scp + restart，详见 docs/kb/deployment.md）
sshpass -p '<pwd>' scp -o StrictHostKeyChecking=no agent/services/<file>.py root@<node>:/opt/perftest-agent/services/
sshpass -p '<pwd>' ssh -o StrictHostKeyChecking=no root@<node> "systemctl restart perftest-agent"
```

**没有测试套件、没有 lint 配置。** 验证靠 `py_compile` + 端到端跑测试 + 查 DB + curl API。

## 架构要点（详见 docs/kb/architecture.md）

- **center/**（本地）：Flask + SQLAlchemy(SQLite) + threading。`routes/api.py` 是 REST+SSE；`services/task_orchestrator.py` 后台线程调度测试；`services/sse_manager.py` 推实时指标到浏览器。
- **agent/**（远程每台节点）：Flask。`routes/agent_api.py` 暴露 `/agent/*`；`services/iperf3_runner.py` 跑 iperf3；`services/cps_tester.py` 测 CPS；`services/metrics_collector.py` 采集 CPU/内存/网卡（SR-IOV 三层回退）；`services/dperf_runner.py` 已存在但 dperf 未编译安装。
- **通信**：center 主动 HTTP 调 agent（agent 不回调 center，避免防火墙问题）。实时指标靠 center 在 `_poll_progress` 里每 3s 轮询两边 `/agent/metrics/current` → SSE 推前端。
- **测试生命周期**（`task_orchestrator._run_test`）：`_start_metrics_parallel` → `_run_iperf_test`/`_run_dperf_test` →（可选 `_run_bidirectional`、`_run_cps`）→ `_cleanup`。**`_cleanup` 必须先 fetch 硬件快照再 stop metrics**（agent 的 metrics/stop 会清空内存缓冲）。

## 指标数据流（详见 docs/kb/metrics-pipeline.md）

| 指标 | 来源 | 入库表 | 前端字段 |
|------|------|--------|----------|
| BPS | iperf3 JSON `end.sum_received.bits_per_second` | `iperf_results.summary_bits_per_sec` | `avg_bw_mbps`/`peak_bw_mbps` |
| PPS | **agent 网卡驱动层统计**（ethtool→sysfs→psutil），非 iperf3（TCP 不报包数） | `hardware_snapshots.network_tx_pps/rx_pps` | `pps_summary`/`avg_pps_kpps` |
| CPS | agent `CpsTester`（50 线程 TCP 建连），`/agent/cps/start` 同步返回 | `cps_results.cps` | `cps_summary` |
| 并发连接 | 当前= `cps_results.connections_succeeded` 之和（非真·最大并发，dperf 未装） | `cps_results` | `conns_succeeded` |

## 关键坑（详见 docs/kb/known-issues.md）

- **center 热重载，agent 不热重载**：改 agent 后必须 scp 到 `/opt/perftest-agent/` + `systemctl restart perftest-agent`，否则远程跑旧代码。本轮 CPS 空数据的根因就是 agent 修复没部署。
- **EIP 带宽限制**：节点在 center 里注册的是 EIP（外网 IP，1M 带宽），但 iperf3/CPS 的 target 必须用 agent `/agent/health` 返回的 `internal_ips[0]`（内网 IP），否则打流受 EIP 限速。
- **SR-IOV 环境**：psutil 读 `/proc/net/dev` 看不到绕过内核的流量，必须用 `ethtool -S` 读驱动层计数（`NetworkStats` 已实现三层回退）。
- **TCP 测试 PPS 恒为 0**：iperf3 对 TCP 不上报 packet 计数，所以 PPS 走硬件网卡统计，不走 `iperf_results.avg_pps`（该字段仅 UDP 有值）。
- **`config.py` 被 gitignore**：`*/config.py` 在 `.gitignore`，center/agent 的 config.py 都是本地文件，改默认端口/路径不会进 git。
- **dperf 未安装**：两台远程节点 `engines.dperf=false`。PPS/CPS/并发当前用 iperf3+Python 方案，非 dperf。真·小包 PPS 和真·最大并发未实现。

## 用户约定（详见 docs/kb/user-workflow.md）

- **不要 git commit/push**——用户明确说过"后续提交和推送操作都由我经过测试后再执行，你不用操作"。
- 改完代码要**精确说出改了 center 还是 agent**，并给出对应的部署步骤。center 改了只需重启 center（热重载）；agent 改了必须 scp + restart 远程两台节点。**不要给模糊的"同步一下"建议**——本轮之前因这个问题误导过用户两次。
- 用户偏好先深析根因再动手，参考主流商业软件方案（AWS/阿里云 SR-IOV PMD 统计）。
- 远程节点凭据见 [docs/kb/deployment.md](docs/kb/deployment.md)。
