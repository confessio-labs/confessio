(function () {
    const charts = JSON.parse(document.getElementById('stats-data').textContent);
    const TEXT_COLOR = '#52514e';
    const GRID_COLOR = '#e8e7e3';
    const SURFACE_COLOR = '#ffffff';

    Chart.defaults.color = TEXT_COLOR;
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;

    function buildDataset(chart, dataset) {
        const type = dataset.type || chart.type;
        const common = {
            label: dataset.label,
            data: dataset.data,
            backgroundColor: dataset.color,
            borderColor: dataset.color,
            yAxisID: dataset.yAxisID || 'y',
        };
        if (type === 'line') {
            return Object.assign(common, {
                type: 'line',
                borderWidth: 2,
                pointRadius: 4,
                pointHoverRadius: 6,
                pointBorderColor: SURFACE_COLOR,
                pointBorderWidth: 2,
                order: 0,
            });
        }
        // A surface-colored top border leaves a gap between stacked segments.
        return Object.assign(common, {
            type: 'bar',
            borderColor: SURFACE_COLOR,
            borderWidth: chart.stacked ? {top: 2} : 0,
            borderRadius: chart.stacked ? 0 : 4,
            order: 1,
        });
    }

    function buildScales(chart) {
        const axis = {
            grid: {color: GRID_COLOR},
            border: {display: false},
            beginAtZero: true,
            stacked: chart.stacked,
        };
        const scales = {
            x: {grid: {display: false}, stacked: chart.stacked},
            y: Object.assign({}, axis, {
                max: chart.y_max,
                title: {display: Boolean(chart.y_title), text: chart.y_title},
            }),
        };
        if (chart.datasets.some(dataset => dataset.yAxisID === 'y2')) {
            scales.y2 = Object.assign({}, axis, {
                position: 'right',
                grid: {drawOnChartArea: false},
                title: {display: true, text: chart.y2_title},
            });
        }
        return scales;
    }

    document.querySelectorAll('canvas[data-chart]').forEach(canvas => {
        const chart = charts[canvas.dataset.chart];
        if (!chart.labels.length) {
            canvas.parentElement.innerHTML = '<p class="text-muted">Aucune donnée.</p>';
            return;
        }
        new Chart(canvas, {
            type: chart.type,
            data: {
                labels: chart.labels,
                datasets: chart.datasets.map(dataset => buildDataset(chart, dataset)),
            },
            options: {
                maintainAspectRatio: false,
                interaction: {mode: 'index', intersect: false},
                plugins: {
                    legend: {
                        display: chart.datasets.length > 1,
                        // Dataset `order` puts lines above bars; the legend keeps the payload order.
                        labels: {
                            boxWidth: 12,
                            boxHeight: 12,
                            sort: (a, b) => a.datasetIndex - b.datasetIndex,
                        },
                    },
                },
                scales: buildScales(chart),
            },
        });
    });
})();
