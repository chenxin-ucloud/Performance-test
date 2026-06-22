/**
 * Chart.js initialization and updates.
 */

// Common chart options for dark theme
const commonOptions = {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 0 },
    interaction: { mode: 'index', intersect: false },
    plugins: {
        legend: {
            labels: { color: '#94a3b8', font: { size: 11 } },
        },
    },
    scales: {
        x: {
            grid: { color: '#334155' },
            ticks: { color: '#94a3b8', font: { size: 10 }, maxTicksLimit: 8 },
        },
        y: {
            grid: { color: '#334155' },
            ticks: { color: '#94a3b8', font: { size: 10 } },
        },
    },
};

const MAX_POINTS = 60;

function createChart(canvasId, label, color, yLabel) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    return new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: label,
                data: [],
                borderColor: color,
                backgroundColor: color + '33',
                fill: true,
                tension: 0.2,
                pointRadius: 0,
                borderWidth: 1.5,
            }],
        },
        options: {
            ...commonOptions,
            plugins: {
                ...commonOptions.plugins,
                title: {
                    display: true,
                    text: label,
                    color: '#f1f5f9',
                    font: { size: 12 },
                },
            },
            scales: {
                ...commonOptions.scales,
                y: {
                    ...commonOptions.scales.y,
                    title: { display: true, text: yLabel, color: '#94a3b8', font: { size: 10 } },
                },
            },
        },
    });
}

function createDualChart(canvasId, label1, color1, label2, color2, yLabel) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    return new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: label1,
                    data: [],
                    borderColor: color1,
                    backgroundColor: color1 + '33',
                    fill: true,
                    tension: 0.2,
                    pointRadius: 0,
                    borderWidth: 1.5,
                },
                {
                    label: label2,
                    data: [],
                    borderColor: color2,
                    backgroundColor: color2 + '33',
                    fill: true,
                    tension: 0.2,
                    pointRadius: 0,
                    borderWidth: 1.5,
                },
            ],
        },
        options: {
            ...commonOptions,
            plugins: {
                ...commonOptions.plugins,
                title: {
                    display: true,
                    text: yLabel,
                    color: '#f1f5f9',
                    font: { size: 12 },
                },
            },
        },
    });
}

function updateChart(chart, label, value) {
    if (!chart) return;
    chart.data.labels.push(label);
    chart.data.datasets[0].data.push(value);
    if (chart.data.labels.length > MAX_POINTS) {
        chart.data.labels.shift();
        chart.data.datasets[0].data.shift();
    }
    chart.update('none');
}

function updateDualChart(chart, label, value1, value2) {
    if (!chart) return;
    chart.data.labels.push(label);
    chart.data.datasets[0].data.push(value1);
    chart.data.datasets[1].data.push(value2);
    if (chart.data.labels.length > MAX_POINTS) {
        chart.data.labels.shift();
        chart.data.datasets[0].data.shift();
        chart.data.datasets[1].data.shift();
    }
    chart.update('none');
}

function resetChart(chart) {
    if (!chart) return;
    chart.data.labels = [];
    chart.data.datasets.forEach(ds => ds.data = []);
    chart.update();
}
