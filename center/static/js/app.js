/**
 * Main application logic for the performance test dashboard.
 */

// ===== State =====
let nodes = [];
let currentTestId = null;
let eventSource = null;
let testStartTime = null;
let refreshInterval = null;

// Charts
let bwChart = null;
let ppsChart = null;
let cpuChart = null;
let memChart = null;

// Peak tracking
let peakBw = 0;
let peakPps = 0;

// ===== Init =====
document.addEventListener('DOMContentLoaded', () => {
    initCharts();
    loadNodes();
    loadHistory();
    setupEventHandlers();

    // Auto-refresh history every 10 seconds when idle
    refreshInterval = setInterval(() => {
        if (!currentTestId) loadHistory();
    }, 10000);
});

function initCharts() {
    bwChart = createChart('bwChart', '带宽 (Mbps)', '#3b82f6', 'Mbps');
    ppsChart = createChart('ppsChart', 'PPS (Kpps)', '#22c55e', 'Kpps');
    cpuChart = createDualChart('cpuChart', '客户端 CPU', '#ef4444', '服务端 CPU', '#f97316', 'CPU %');
    memChart = createDualChart('memChart', '客户端内存', '#8b5cf6', '服务端内存', '#a855f7', '内存 %');
}

function setupEventHandlers() {
    document.getElementById('addNodeForm').addEventListener('submit', onAddNode);
    document.getElementById('testConfigForm').addEventListener('submit', onStartTest);
    document.getElementById('stopTestBtn').addEventListener('click', onStopTest);
    document.getElementById('modalClose').addEventListener('click', closeModal);
}

// ===== Nodes =====

async function loadNodes() {
    try {
        nodes = await getNodes();
        renderNodes();
        populateNodeSelects();
    } catch (e) {
        console.error('Failed to load nodes:', e);
    }
}

function renderNodes() {
    const tbody = document.getElementById('nodeTableBody');
    tbody.innerHTML = nodes.map(n => `
        <tr>
            <td>${escapeHtml(n.name)}</td>
            <td>${escapeHtml(n.host)}:${n.agent_port}</td>
            <td class="status-${n.status || 'unknown'}">${n.status || 'unknown'}</td>
            <td>
                <button class="btn-small" onclick="checkNode(${n.id})">检测</button>
                <button class="btn-small" onclick="removeNode(${n.id})">删除</button>
            </td>
        </tr>
    `).join('');
}

function populateNodeSelects() {
    const clientSel = document.getElementById('clientNode');
    const serverSel = document.getElementById('serverNode');
    const options = nodes.map(n => `<option value="${n.id}">${escapeHtml(n.name)} (${escapeHtml(n.host)})</option>`).join('');
    clientSel.innerHTML = options;
    serverSel.innerHTML = options;
    if (nodes.length >= 2) {
        serverSel.selectedIndex = 1;
    }
}

async function onAddNode(e) {
    e.preventDefault();
    const data = {
        name: document.getElementById('nodeName').value,
        host: document.getElementById('nodeHost').value,
        agent_port: parseInt(document.getElementById('nodePort').value) || 5002,
        description: document.getElementById('nodeDesc').value,
    };
    try {
        await addNode(data);
        document.getElementById('addNodeForm').reset();
        loadNodes();
    } catch (e) {
        alert('添加节点失败: ' + e.message);
    }
}

async function removeNode(id) {
    if (!confirm('确定删除该节点?')) return;
    try {
        await deleteNode(id);
        loadNodes();
    } catch (e) {
        alert('删除失败: ' + e.message);
    }
}

async function checkNode(id) {
    try {
        const result = await checkNodeHealth(id);
        alert('节点状态: ' + (result.status === 'online' ? '在线' : '离线'));
        loadNodes();
    } catch (e) {
        alert('检测失败: ' + e.message);
        loadNodes();
    }
}

// ===== Tests =====

async function onStartTest(e) {
    e.preventDefault();
    if (currentTestId) {
        alert('已有测试正在运行');
        return;
    }

    const clientNodeId = parseInt(document.getElementById('clientNode').value);
    const serverNodeId = parseInt(document.getElementById('serverNode').value);

    if (clientNodeId === serverNodeId) {
        alert('客户端和服务端不能是同一个节点');
        return;
    }

    const config = {
        client_node_id: clientNodeId,
        server_node_id: serverNodeId,
        test_type: document.querySelector('input[name="protocol"]:checked').value,
        duration_sec: parseInt(document.getElementById('duration').value) || 10,
        parallel_streams: parseInt(document.getElementById('parallelStreams').value) || 1,
        bandwidth_limit: document.getElementById('bandwidthLimit').value || null,
        reverse_mode: document.getElementById('reverseMode').checked,
        bidirectional: document.getElementById('bidirectional').checked,
        measure_cps: document.getElementById('measureCps').checked,
    };

    try {
        const result = await startTest(config);
        currentTestId = result.test_id;
        testStartTime = Date.now();
        peakBw = 0;
        peakPps = 0;

        resetChart(bwChart);
        resetChart(ppsChart);
        resetChart(cpuChart);
        resetChart(memChart);

        updateStatus('running', '测试运行中...');
        document.getElementById('startTestBtn').disabled = true;
        document.getElementById('stopTestBtn').disabled = false;

        // Connect SSE
        eventSource = connectStream(currentTestId, onStreamMessage, onStreamError);
    } catch (e) {
        alert('启动测试失败: ' + e.message);
    }
}

async function onStopTest() {
    if (!currentTestId) return;
    try {
        await stopTest(currentTestId);
        updateStatus('interrupted', '测试已中断');
    } catch (e) {
        console.error('Stop test failed:', e);
    }
}

function onStreamMessage(data) {
    if (data.type === 'status') {
        if (data.status === 'completed' || data.status === 'interrupted' || data.status === 'failed') {
            const msg = data.error ? ('失败: ' + data.error) : (data.message || '');
            finishTest(data.status, msg);
        } else {
            updateStatus(data.status, data.message || '运行中...');
        }
        return;
    }

    if (data.type !== 'metrics') return;

    const elapsed = data.elapsed || 0;
    const label = elapsed + 's';

    const client = data.client || {};
    const server = data.server || {};

    // CPU / Memory
    updateDualChart(cpuChart, label, client.cpu_percent || 0, server.cpu_percent || 0);
    updateDualChart(memChart, label, client.memory_percent || 0, server.memory_percent || 0);

    // Bandwidth: use client tx (outbound from client) as the test bandwidth
    const bwClient = client.network_tx_mbps || 0;
    const bwServer = server.network_rx_mbps || 0;
    const bw = Math.max(bwClient, bwServer);
    if (bw > peakBw) peakBw = bw;
    updateChart(bwChart, label, bw);

    // PPS: use max of client tx pps and server rx pps
    const ppsClient = client.network_tx_pps || 0;
    const ppsServer = server.network_rx_pps || 0;
    const pps = Math.max(ppsClient, ppsServer);
    if (pps > peakPps) peakPps = pps;
    updateChart(ppsChart, label, pps / 1000); // show in Kpps

    // Update metric cards
    document.getElementById('bwValue').textContent = bw.toFixed(2) + ' Mbps';
    document.getElementById('bwPeak').textContent = '峰值: ' + peakBw.toFixed(2) + ' Mbps';
    document.getElementById('ppsValue').textContent = (pps / 1000).toFixed(2) + ' Kpps';
    document.getElementById('ppsPeak').textContent = '峰值: ' + (peakPps / 1000).toFixed(2) + ' Kpps';
    document.getElementById('clientCpu').textContent = (client.cpu_percent || 0).toFixed(1) + '%';
    document.getElementById('serverCpu').textContent = (server.cpu_percent || 0).toFixed(1) + '%';
    document.getElementById('clientMem').textContent = (client.memory_percent || 0).toFixed(1) + '%';
    document.getElementById('serverMem').textContent = (server.memory_percent || 0).toFixed(1) + '%';

    // Timer
    const elapsedSec = Math.floor((Date.now() - testStartTime) / 1000);
    document.getElementById('timer').textContent = formatDuration(elapsedSec);
}

function onStreamError(e) {
    console.error('SSE error:', e);
    finishTest('failed');
}

async function finishTest(status, errorMsg) {
    if (eventSource) {
        eventSource.close();
        eventSource = null;
    }
    currentTestId = null;
    testStartTime = null;

    let msg;
    if (status === 'completed') msg = '测试完成';
    else if (status === 'interrupted') msg = '测试中断';
    else msg = '测试失败' + (errorMsg ? ': ' + errorMsg : '');
    updateStatus(status, msg);

    document.getElementById('startTestBtn').disabled = false;
    document.getElementById('stopTestBtn').disabled = true;
    document.getElementById('timer').textContent = '';

    setTimeout(loadHistory, 500);
}

// ===== History =====

async function loadHistory() {
    try {
        const data = await getTests();
        renderHistory(data.items || []);
    } catch (e) {
        console.error('Failed to load history:', e);
    }
}

function renderHistory(tests) {
    const tbody = document.getElementById('historyTableBody');
    tbody.innerHTML = tests.map(t => {
        const clientName = t.client_node ? t.client_node.name : '?';
        const serverName = t.server_node ? t.server_node.name : '?';
        const statusClass = `status-${t.status}`;
        return `
        <tr onclick="showTestDetail(${t.id})" style="cursor:pointer">
            <td>${t.id}</td>
            <td>${escapeHtml(t.name || '-')}</td>
            <td>${escapeHtml(clientName)} → ${escapeHtml(serverName)}</td>
            <td>${t.test_type.toUpperCase()}</td>
            <td>${t.duration_sec}s</td>
            <td>${t.parallel_streams}</td>
            <td>-</td>
            <td>-</td>
            <td>-</td>
            <td class="${statusClass}">${t.status}</td>
            <td>${formatDate(t.started_at)}</td>
            <td>
                <button class="btn-small" onclick="event.stopPropagation(); deleteTestItem(${t.id})">删除</button>
            </td>
        </tr>
        `;
    }).join('');
}

async function deleteTestItem(id) {
    if (!confirm('确定删除该测试记录?')) return;
    try {
        await deleteTest(id);
        loadHistory();
    } catch (e) {
        alert('删除失败: ' + e.message);
    }
}

// ===== Test Detail Modal =====

async function showTestDetail(testId) {
    try {
        const [testData, resultsData, cpsData, hwData] = await Promise.all([
            getTest(testId),
            getResults(testId),
            getCps(testId),
            getHardware(testId),
        ]);

        const test = testData;
        const results = resultsData.results || [];
        const cps = cpsData || [];

        let html = `<div class="detail-section">`;
        html += `<h3>测试 #${test.id} — ${escapeHtml(test.name || '未命名')}</h3>`;
        html += `<p><strong>客户端:</strong> ${test.client_node ? test.client_node.name : '?'} → <strong>服务端:</strong> ${test.server_node ? test.server_node.name : '?'}</p>`;
        html += `<p><strong>协议:</strong> ${test.test_type.toUpperCase()} | <strong>时长:</strong> ${test.duration_sec}s | <strong>流数:</strong> ${test.parallel_streams}</p>`;
        html += `<p><strong>状态:</strong> <span class="status-${test.status}">${test.status}</span></p>`;

        // Iperf results
        if (results.length > 0) {
            html += `<h4>Iperf3 结果</h4>`;
            html += `<table class="detail-table">`;
            html += `<tr><th>节点</th><th>角色</th><th>带宽</th><th>字节</th><th>包数</th><th>PPS</th><th>重传</th></tr>`;
            for (const r of results) {
                html += `<tr>
                    <td>${escapeHtml(r.node_name || '?')}</td>
                    <td>${r.role}</td>
                    <td>${formatBits(r.summary_bits_per_sec)}</td>
                    <td>${formatBytes(r.summary_bytes)}</td>
                    <td>${r.summary_packets || '-'}</td>
                    <td>${formatPps(r.avg_pps)}</td>
                    <td>${r.retransmits || '-'}</td>
                </tr>`;
            }
            html += `</table>`;

            // Raw JSON download links
            html += `<div class="detail-actions">`;
            for (const r of results) {
                html += `<a class="btn-small" href="/api/tests/${testId}/results/${r.id}/raw" target="_blank">下载 ${escapeHtml(r.node_name || '?')} JSON</a> `;
            }
            html += `</div>`;
        }

        // CPS results
        if (cps.length > 0) {
            html += `<h4>CPS 结果</h4>`;
            html += `<table class="detail-table">`;
            html += `<tr><th>源节点</th><th>目标节点</th><th>CPS</th><th>成功/尝试</th><th>耗时</th></tr>`;
            for (const c of cps) {
                html += `<tr>
                    <td>${escapeHtml(c.source_node_name || '?')}</td>
                    <td>${escapeHtml(c.target_node_name || '?')}</td>
                    <td>${formatCps(c.cps)}</td>
                    <td>${c.connections_succeeded || 0} / ${c.connections_attempted || 0}</td>
                    <td>${c.duration_ms}ms</td>
                </tr>`;
            }
            html += `</table>`;
        }

        // Hardware snapshots chart (placeholder: we could render a chart from hwData)
        if (hwData.length > 0) {
            html += `<h4>硬件指标</h4>`;
            html += `<p>共采集 ${hwData.length} 个样本</p>`;
        }

        html += `</div>`;

        document.getElementById('detailContent').innerHTML = html;
        document.getElementById('detailModal').classList.add('active');
    } catch (e) {
        alert('加载详情失败: ' + e.message);
    }
}

function closeModal() {
    document.getElementById('detailModal').classList.remove('active');
}

// ===== Helpers =====

function updateStatus(status, message) {
    const bar = document.querySelector('.status-bar .status-text');
    bar.textContent = message;
    bar.className = 'status-text status-' + status;
}

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;')
              .replace(/</g, '&lt;')
              .replace(/>/g, '&gt;')
              .replace(/"/g, '&quot;');
}

function formatDuration(seconds) {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
}

function formatDate(iso) {
    if (!iso) return '-';
    const d = new Date(iso);
    return d.toLocaleString('zh-CN');
}

function formatBits(bps) {
    if (!bps) return '-';
    if (bps >= 1e9) return (bps / 1e9).toFixed(2) + ' Gbps';
    if (bps >= 1e6) return (bps / 1e6).toFixed(2) + ' Mbps';
    if (bps >= 1e3) return (bps / 1e3).toFixed(2) + ' Kbps';
    return bps.toFixed(2) + ' bps';
}

function formatBytes(bytes) {
    if (!bytes) return '-';
    if (bytes >= 1024 ** 3) return (bytes / (1024 ** 3)).toFixed(2) + ' GB';
    if (bytes >= 1024 ** 2) return (bytes / (1024 ** 2)).toFixed(2) + ' MB';
    if (bytes >= 1024) return (bytes / 1024).toFixed(2) + ' KB';
    return bytes + ' B';
}

function formatPps(pps) {
    if (!pps) return '-';
    if (pps >= 1e6) return (pps / 1e6).toFixed(2) + ' Mpps';
    if (pps >= 1e3) return (pps / 1e3).toFixed(2) + ' Kpps';
    return pps.toFixed(2) + ' pps';
}

function formatCps(cps) {
    if (!cps) return '-';
    if (cps >= 1e6) return (cps / 1e6).toFixed(2) + ' Mcps';
    if (cps >= 1e3) return (cps / 1e3).toFixed(2) + ' Kcps';
    return cps.toFixed(2) + ' cps';
}
