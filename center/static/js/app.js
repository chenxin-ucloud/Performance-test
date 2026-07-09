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
    document.getElementById('editNodeForm').addEventListener('submit', onEditNode);
    document.getElementById('nodeEditClose').addEventListener('click', closeNodeEditModal);
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
                <button class="btn-small" onclick="editNode(${n.id})">编辑</button>
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

function editNode(id) {
    const n = nodes.find(x => x.id === id);
    if (!n) return;
    document.getElementById('editNodeId').value = n.id;
    document.getElementById('editNodeName').value = n.name || '';
    document.getElementById('editNodeHost').value = n.host || '';
    document.getElementById('editNodePort').value = n.agent_port || 5002;
    document.getElementById('editNodeDesc').value = n.description || '';
    document.getElementById('nodeEditModal').classList.add('active');
}

function closeNodeEditModal() {
    document.getElementById('nodeEditModal').classList.remove('active');
}

async function onEditNode(e) {
    e.preventDefault();
    const id = parseInt(document.getElementById('editNodeId').value);
    const data = {
        name: document.getElementById('editNodeName').value,
        host: document.getElementById('editNodeHost').value,
        agent_port: parseInt(document.getElementById('editNodePort').value) || 5002,
        description: document.getElementById('editNodeDesc').value,
    };
    try {
        await updateNode(id, data);
        closeNodeEditModal();
        loadNodes();
    } catch (e) {
        alert('保存失败: ' + e.message);
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
        name: (document.getElementById('testName').value || '').trim(),
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

        // Start local timer as fallback when SSE is unstable during heavy traffic
        startLocalTimer();

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

// ===== Local timer (fallback when SSE is unstable during heavy traffic) =====
let localTimerInterval = null;

function startLocalTimer() {
    stopLocalTimer();
    localTimerInterval = setInterval(() => {
        if (testStartTime) {
            const elapsedSec = Math.floor((Date.now() - testStartTime) / 1000);
            document.getElementById('timer').textContent = formatDuration(elapsedSec);
        }
    }, 1000);
}

function stopLocalTimer() {
    if (localTimerInterval) {
        clearInterval(localTimerInterval);
        localTimerInterval = null;
    }
}

async function finishTest(status, errorMsg) {
    stopLocalTimer();
    if (eventSource) {
        eventSource.close();
        eventSource = null;
    }
    const finishedTestId = currentTestId;
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

    // Fetch final results and update metric cards
    if (finishedTestId && status === 'completed') {
        try {
            const results = await getResults(finishedTestId);
            const iperf = results.iperf_results || [];
            const cps = results.cps_results || [];
            const ppsSummary = results.pps_summary || {};
            const cpsSummary = results.cps_summary || null;

            if (iperf.length > 0) {
                const bws = iperf.map(r => r.summary_bits_per_sec).filter(v => v);
                const avgBw = bws.length ? (bws.reduce((a, b) => a + b, 0) / bws.length / 1e6) : 0;
                const peakBw = bws.length ? Math.max(...bws) / 1e6 : 0;

                document.getElementById('bwValue').textContent = avgBw.toFixed(2) + ' Mbps';
                document.getElementById('bwPeak').textContent = '峰值: ' + peakBw.toFixed(2) + ' Mbps';

                // Prefer hardware-derived PPS (accurate for TCP); fall back to
                // iperf3 avg_pps (only populated for UDP) when no NIC PPS data.
                const avgPps = ppsSummary.avg_pps_kpps != null
                    ? ppsSummary.avg_pps_kpps
                    : (iperf.map(r => r.avg_pps).filter(v => v).reduce((a, b) => a + b, 0) / 1e3 || 0);
                const peakPps = ppsSummary.peak_pps_kpps != null
                    ? ppsSummary.peak_pps_kpps
                    : 0;
                document.getElementById('ppsValue').textContent = avgPps.toFixed(2) + ' Kpps';
                document.getElementById('ppsPeak').textContent = '峰值: ' + peakPps.toFixed(2) + ' Kpps';
            }

            // CPS + concurrent connections from the dedicated CPS measurement
            if (cpsSummary) {
                document.getElementById('cpsValue').textContent =
                    (cpsSummary.cps != null ? cpsSummary.cps : 0).toFixed(0) + ' cps';
                document.getElementById('connValue').textContent =
                    (cpsSummary.conns_succeeded || 0).toLocaleString();
            } else if (cps.length > 0) {
                const cpsVals = cps.map(r => r.cps).filter(v => v);
                const avgCps = cpsVals.length ? (cpsVals.reduce((a, b) => a + b, 0) / cpsVals.length) : 0;
                const conns = cps.reduce((sum, r) => sum + (r.connections_succeeded || 0), 0);
                document.getElementById('cpsValue').textContent = avgCps.toFixed(0) + ' cps';
                document.getElementById('connValue').textContent = conns.toLocaleString();
            }
        } catch (e) {
            console.error('Failed to load final results:', e);
        }
    }

    setTimeout(loadHistory, 500);
}

// ===== History =====

// Sort/filter state for the history table (persisted across reloads within a session)
let historySort = { field: 'started_at', order: 'desc' };
let historyFilter = { protocol: '', status: '' };
let activeFilterMenu = null;

function sortBy(field) {
    if (historySort.field === field) {
        historySort.order = historySort.order === 'desc' ? 'asc' : 'desc';
    } else {
        historySort.field = field;
        historySort.order = 'asc';
    }
    updateSortIndicators();
    loadHistory();
}

function toggleFilterMenu(field, event) {
    event.stopPropagation();
    const pop = document.getElementById('filter-popover-' + field);
    if (!pop) return;
    // Already open? close it.
    if (pop.classList.contains('active')) {
        closeFilterMenus();
        return;
    }
    // Close any other open popover first
    closeFilterMenus();
    // Position the fixed popover under the funnel icon, flipping left if it
    // would overflow the viewport (status column sits near the right edge).
    const funnel = event.currentTarget;
    const r = funnel.getBoundingClientRect();
    const popW = pop.offsetWidth || 120;
    let left = r.left;
    if (left + popW > window.innerWidth - 8) left = window.innerWidth - popW - 8;
    if (left < 8) left = 8;
    pop.style.top = (r.bottom + 4) + 'px';
    pop.style.left = left + 'px';
    pop.classList.add('active');
    activeFilterMenu = field;
    // Highlight the currently selected option
    const current = historyFilter[field];
    pop.querySelectorAll('.filter-option').forEach(opt => {
        opt.classList.toggle('selected', opt.dataset.value === current);
    });
}

function filterBy(field, value) {
    historyFilter[field] = value;
    closeFilterMenus();
    updateFilterChips();
    loadHistory();
}

function closeFilterMenus() {
    document.querySelectorAll('.filter-popover.active').forEach(p => p.classList.remove('active'));
    activeFilterMenu = null;
}

function clearFilters() {
    historyFilter = { protocol: '', status: '' };
    closeFilterMenus();
    updateFilterChips();
    loadHistory();
}

function updateFilterChips() {
    // Funnel icon turns blue when its filter is active
    document.querySelectorAll('.funnel').forEach(f => {
        f.classList.toggle('active', !!historyFilter[f.dataset.field]);
    });
    // Show "返回列表" button only when any filter is active
    const hasFilter = historyFilter.protocol || historyFilter.status;
    const btn = document.getElementById('clearFilterBtn');
    if (btn) btn.style.display = hasFilter ? '' : 'none';
}

function updateSortIndicators() {
    document.querySelectorAll('.sort-indicator').forEach(el => { el.textContent = ''; });
    const el = document.getElementById('sort-' + historySort.field);
    if (el) el.textContent = historySort.order === 'desc' ? '▼' : '▲';
}

// Close any open filter popover when clicking outside the header or popover
document.addEventListener('click', (e) => {
    if (activeFilterMenu && !e.target.closest('.th-filterable') && !e.target.closest('.filter-popover')) {
        closeFilterMenus();
    }
});

async function loadHistory() {
    try {
        const data = await getTests(1, 20, historySort, historyFilter);
        renderHistory(data.items || []);
        updateSortIndicators();
        updateFilterChips();
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
        const bwDisplay = t.avg_bw_mbps != null ? t.avg_bw_mbps.toFixed(2) + ' Mbps' : '-';
        const peakBwDisplay = t.peak_bw_mbps != null ? t.peak_bw_mbps.toFixed(2) + ' Mbps' : '-';
        const ppsDisplay = t.avg_pps_kpps != null ? t.avg_pps_kpps.toFixed(2) + ' Kpps' : '-';
        const cpsDisplay = t.cps != null ? t.cps.toFixed(0) + ' cps' : '-';
        const connDisplay = t.conns_succeeded != null ? t.conns_succeeded.toLocaleString() : '-';
        return `
        <tr onclick="showTestDetail(${t.id})" style="cursor:pointer">
            <td>${t.id}</td>
            <td>${escapeHtml(t.name || '-')}</td>
            <td>${escapeHtml(clientName)} → ${escapeHtml(serverName)}</td>
            <td>${t.test_type.toUpperCase()}</td>
            <td>${t.duration_sec}s</td>
            <td>${t.parallel_streams}</td>
            <td>${bwDisplay}</td>
            <td>${peakBwDisplay}</td>
            <td>${ppsDisplay}</td>
            <td>${cpsDisplay}</td>
            <td>${connDisplay}</td>
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

function pct(v) { return v == null ? '-' : (typeof v === 'number' ? v.toFixed(1) + '%' : v); }
function num(v, digits = 2) { return v == null ? '-' : (typeof v === 'number' ? v.toFixed(digits) : v); }

function aggregateHardware(hwSnaps) {
    if (!Array.isArray(hwSnaps) || hwSnaps.length === 0) return [];
    const byNode = {};
    for (const s of hwSnaps) {
        const key = s.node_name || ('node-' + s.node_id);
        if (!byNode[key]) {
            byNode[key] = { name: key, cpu: 0, mem: 0, tx_mbps: 0, rx_mbps: 0, tx_pps: 0, rx_pps: 0, count: 0 };
        }
        const agg = byNode[key];
        agg.count++;
        agg.cpu = Math.max(agg.cpu, s.cpu_percent || 0);
        agg.mem = Math.max(agg.mem, s.memory_percent || 0);
        agg.tx_mbps = Math.max(agg.tx_mbps, s.network_tx_mbps || 0);
        agg.rx_mbps = Math.max(agg.rx_mbps, s.network_rx_mbps || 0);
        agg.tx_pps = Math.max(agg.tx_pps, s.network_tx_pps || 0);
        agg.rx_pps = Math.max(agg.rx_pps, s.network_rx_pps || 0);
    }
    return Object.values(byNode);
}

async function showTestDetail(testId) {
    try {
        const [testData, resultsData, cpsData, hwData] = await Promise.all([
            getTest(testId),
            getResults(testId),
            getCps(testId),
            getHardware(testId),
        ]);

        const test = testData;
        const iperfResults = resultsData.iperf_results || [];
        const dperfResults = resultsData.dperf_results || [];
        const cps = cpsData || [];
        const ppsSummary = resultsData.pps_summary || {};
        const cpsSummary = resultsData.cps_summary || null;
        const hwAgg = aggregateHardware(hwData);

        const clientName = test.client_node ? test.client_node.name : '?';
        const serverName = test.server_node ? test.server_node.name : '?';

        // --- Header ---
        let html = `<div class="detail-section">`;
        html += `<div class="detail-header">
            <div>
                <div class="detail-title">测试 #${test.id} — ${escapeHtml(test.name || '未命名')}</div>
                <div class="detail-subtitle">${formatDate(test.started_at)}${test.completed_at ? ' → ' + formatDate(test.completed_at) : ''}</div>
            </div>
            <span class="status-badge status-${test.status}">${test.status}</span>
        </div>`;

        // --- Meta grid ---
        const hasBw = iperfResults.some(r => r.summary_bits_per_sec);
        const avgBw = hasBw ? (iperfResults.map(r => r.summary_bits_per_sec).filter(Boolean).reduce((a, b) => a + b, 0) / iperfResults.filter(r => r.summary_bits_per_sec).length / 1e6) : null;
        html += `<div class="detail-meta">
            <div class="detail-meta-item"><div class="label">客户端 → 服务端</div><div class="value">${escapeHtml(clientName)} → ${escapeHtml(serverName)}</div></div>
            <div class="detail-meta-item"><div class="label">协议 / 引擎</div><div class="value">${test.test_type.toUpperCase()} / ${test.engine || 'iperf3'}</div></div>
            <div class="detail-meta-item"><div class="label">时长 / 流数</div><div class="value">${test.duration_sec}s / ${test.parallel_streams}</div></div>
            <div class="detail-meta-item"><div class="label">带宽限制</div><div class="value">${test.bandwidth_limit || '不限'}</div></div>
            <div class="detail-meta-item"><div class="label">测试选项</div><div class="value">${[
                test.reverse_mode ? '反向' : '',
                test.bidirectional ? '双向' : '',
                test.measure_cps ? '测CPS' : '',
                test.measure_pps ? '测PPS' : '',
                test.measure_concurrent ? '测并发' : '',
            ].filter(Boolean).join(' · ') || '默认'}</div></div>
        </div>`;

        // --- KPI cards ---
        const peakBw = hasBw ? Math.max(...iperfResults.map(r => r.summary_bits_per_sec).filter(Boolean)) / 1e6 : null;
        const kpis = [
            { label: '平均带宽', value: avgBw != null ? avgBw.toFixed(2) : '-', sub: 'Mbps' },
            { label: '峰值带宽', value: peakBw != null ? peakBw.toFixed(2) : '-', sub: 'Mbps' },
            { label: '平均 PPS', value: ppsSummary.avg_pps_kpps != null ? ppsSummary.avg_pps_kpps.toFixed(2) : '-', sub: 'Kpps' },
            { label: '峰值 PPS', value: ppsSummary.peak_pps_kpps != null ? ppsSummary.peak_pps_kpps.toFixed(2) : '-', sub: 'Kpps' },
            { label: 'CPS', value: cpsSummary && cpsSummary.cps != null ? num(cpsSummary.cps, 0) : (cps.length ? formatCps(cps[0].cps) : '-'), sub: 'cps' },
            { label: '并发连接', value: cpsSummary && cpsSummary.conns_succeeded != null ? cpsSummary.conns_succeeded.toLocaleString() : (test.parallel_streams > 1 ? test.parallel_streams + ' (流)' : '-'), sub: '成功建连' },
        ];
        html += `<div class="detail-kpis">`;
        for (const k of kpis) {
            html += `<div class="detail-kpi"><div class="kpi-label">${k.label}</div><div class="kpi-value">${k.value}</div><div class="kpi-sub">${k.sub}</div></div>`;
        }
        html += `</div>`;

        // --- Iperf3 results ---
        if (iperfResults.length > 0) {
            html += `<div class="detail-block">`;
            html += `<h4>Iperf3 结果</h4>`;
            html += `<table class="detail-table">`;
            html += `<tr><th>节点</th><th>角色</th><th class="num">带宽</th><th class="num">字节</th><th class="num">包数</th><th class="num">PPS</th><th class="num">重传</th></tr>`;
            for (const r of iperfResults) {
                html += `<tr>
                    <td>${escapeHtml(r.node_name || '?')}</td>
                    <td>${r.role}</td>
                    <td class="num">${formatBits(r.summary_bits_per_sec)}</td>
                    <td class="num">${formatBytes(r.summary_bytes)}</td>
                    <td class="num">${r.summary_packets != null ? r.summary_packets.toLocaleString() : '-'}</td>
                    <td class="num">${formatPps(r.avg_pps)}</td>
                    <td class="num">${r.retransmits != null ? r.retransmits.toLocaleString() : '-'}</td>
                </tr>`;
            }
            html += `</table>`;
            html += `<div class="detail-actions">`;
            for (const r of iperfResults) {
                html += `<a class="btn-small" href="/api/tests/${testId}/results/${r.id}/raw" target="_blank">下载 ${escapeHtml(r.node_name || '?')} 原始 JSON</a>`;
            }
            html += `</div>`;
            html += `</div>`;
        }

        // --- CPS results ---
        if (cps.length > 0) {
            html += `<div class="detail-block">`;
            html += `<h4>CPS 结果</h4>`;
            html += `<table class="detail-table">`;
            html += `<tr><th>源节点</th><th>目标节点</th><th class="num">CPS</th><th class="num">成功 / 尝试</th><th class="num">成功率</th><th class="num">耗时</th></tr>`;
            for (const c of cps) {
                const rate = c.connections_attempted ? (c.connections_succeeded / c.connections_attempted * 100) : 0;
                html += `<tr>
                    <td>${escapeHtml(c.source_node_name || '?')}</td>
                    <td>${escapeHtml(c.target_node_name || '?')}</td>
                    <td class="num">${formatCps(c.cps)}</td>
                    <td class="num">${(c.connections_succeeded || 0).toLocaleString()} / ${(c.connections_attempted || 0).toLocaleString()}</td>
                    <td class="num">${rate.toFixed(1)}%</td>
                    <td class="num">${c.duration_ms != null ? c.duration_ms.toLocaleString() + ' ms' : '-'}</td>
                </tr>`;
            }
            html += `</table>`;
            html += `</div>`;
        }

        // --- dperf results ---
        if (dperfResults.length > 0) {
            html += `<div class="detail-block">`;
            html += `<h4>dperf 结果</h4>`;
            html += `<table class="detail-table">`;
            html += `<tr><th>节点</th><th>类型</th><th class="num">发送包</th><th class="num">发送字节</th><th class="num">CPS</th><th class="num">并发数</th></tr>`;
            for (const r of dperfResults) {
                html += `<tr>
                    <td>${escapeHtml(r.node_name || '?')}</td>
                    <td>${r.dperf_type}</td>
                    <td class="num">${r.snd_packets != null ? r.snd_packets.toLocaleString() : '-'}</td>
                    <td class="num">${formatBytes(r.snd_bytes)}</td>
                    <td class="num">${r.cps != null ? num(r.cps, 0) : '-'}</td>
                    <td class="num">${r.concurrent != null ? r.concurrent.toLocaleString() : '-'}</td>
                </tr>`;
            }
            html += `</table>`;
            html += `</div>`;
        }

        // --- Hardware peaks ---
        if (hwAgg.length > 0) {
            html += `<div class="detail-block">`;
            html += `<h4>硬件监控峰值（${hwAgg[0].count > 0 ? hwAgg.map(n => n.name + ':' + n.count + '点').join(' · ') : ''}）</h4>`;
            html += `<table class="detail-table">`;
            html += `<tr><th>节点</th><th class="num">CPU 峰值</th><th class="num">内存峰值</th><th class="num">TX 带宽</th><th class="num">RX 带宽</th><th class="num">TX PPS</th><th class="num">RX PPS</th></tr>`;
            for (const n of hwAgg) {
                html += `<tr>
                    <td>${escapeHtml(n.name)}</td>
                    <td class="num">${pct(n.cpu)}</td>
                    <td class="num">${pct(n.mem)}</td>
                    <td class="num">${n.tx_mbps.toFixed(2)} Mbps</td>
                    <td class="num">${n.rx_mbps.toFixed(2)} Mbps</td>
                    <td class="num">${formatPps(n.tx_pps)}</td>
                    <td class="num">${formatPps(n.rx_pps)}</td>
                </tr>`;
            }
            html += `</table>`;
            html += `</div>`;
        }

        // --- Empty state ---
        if (iperfResults.length === 0 && cps.length === 0 && dperfResults.length === 0 && hwAgg.length === 0) {
            html += `<div class="detail-empty">该测试暂无结果数据。</div>`;
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
