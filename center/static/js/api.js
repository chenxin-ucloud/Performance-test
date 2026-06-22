/**
 * API client for the center service.
 */
const API_BASE = '';

async function apiGet(path) {
    const resp = await fetch(`${API_BASE}${path}`);
    if (!resp.ok) throw new Error(`GET ${path} failed: ${resp.status}`);
    return resp.json();
}

async function apiPost(path, data = {}) {
    const resp = await fetch(`${API_BASE}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    });
    if (!resp.ok) throw new Error(`POST ${path} failed: ${resp.status}`);
    return resp.json();
}

async function apiDelete(path) {
    const resp = await fetch(`${API_BASE}${path}`, { method: 'DELETE' });
    if (!resp.ok) throw new Error(`DELETE ${path} failed: ${resp.status}`);
    return resp.json();
}

// Nodes
const getNodes = () => apiGet('/api/nodes');
const addNode = (data) => apiPost('/api/nodes', data);
const deleteNode = (id) => apiDelete(`/api/nodes/${id}`);
const checkNodeHealth = (id) => apiGet(`/api/nodes/${id}/health`);

// Tests
const getTests = (page = 1, perPage = 20) => apiGet(`/api/tests?page=${page}&per_page=${perPage}`);
const getTest = (id) => apiGet(`/api/tests/${id}`);
const startTest = (config) => apiPost('/api/tests/start', config);
const stopTest = (id) => apiPost(`/api/tests/${id}/stop`);
const deleteTest = (id) => apiDelete(`/api/tests/${id}`);

// Results
const getResults = (id) => apiGet(`/api/tests/${id}/results`);
const getCps = (id) => apiGet(`/api/tests/${id}/cps`);
const getHardware = (id, nodeId = null) => {
    let url = `/api/tests/${id}/hardware`;
    if (nodeId) url += `?node_id=${nodeId}`;
    return apiGet(url);
};

// SSE
function connectStream(testId, onMessage, onError) {
    const evtSource = new EventSource(`/api/stream/${testId}`);
    evtSource.onmessage = (e) => {
        try {
            const data = JSON.parse(e.data);
            if (Object.keys(data).length === 0) return; // keepalive
            onMessage(data);
        } catch (err) {
            console.warn('SSE parse error:', err);
        }
    };
    evtSource.onerror = (e) => {
        console.error('SSE error:', e);
        if (onError) onError(e);
        evtSource.close();
    };
    return evtSource;
}
