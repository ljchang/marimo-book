# Raw plotly output

This page verifies that Material/markdown lets us drop in a plotly `<div>` +
inline `<script>` the way marimo's `export html` does. (Real marimo output
would inline the plotly runtime too; for this spike we load it from CDN.)

<div id="plotly-chart" style="width: 100%; height: 320px;"></div>

<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>

<script>
  (function () {
    const data = [{
      type: 'scatter',
      mode: 'lines+markers',
      x: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
      y: [0.2, 0.5, 0.9, 1.1, 0.8, 0.3, -0.1, -0.4, -0.2, 0.1],
      name: 'BOLD-ish',
      line: { color: '#00693E' }
    }];
    const layout = {
      margin: { t: 20, l: 40, r: 10, b: 30 },
      xaxis: { title: 't (TR)' },
      yaxis: { title: 'signal' }
    };
    if (typeof Plotly !== 'undefined') {
      Plotly.newPlot('plotly-chart', data, layout, {displayModeBar: false});
    }
  })();
</script>
