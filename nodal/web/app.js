/* Nodal workbench: six tabs over the pure-Python kernel. No frameworks. */
"use strict";

const $ = (id) => document.getElementById(id);
const COLORS = ["#2dd4bf", "#fbbf24", "#60a5fa", "#f87171", "#a78bfa",
                "#4ade80", "#fb923c", "#e879f9"];

let EXAMPLES = {};

/* ---------------------------------------------------------------- utils */
async function api(path, payload) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function showError(id, err) {
  const el = $(id);
  el.textContent = String(err.message || err);
  el.classList.remove("hidden");
}
function clearError(id) { $(id).classList.add("hidden"); }

function status(text, cls) {
  $("status-text").textContent = text;
  $("status-dot").className = "dot " + (cls || "");
}

const SUFFIX = { t: 1e12, g: 1e9, meg: 1e6, k: 1e3, m: 1e-3,
                 u: 1e-6, n: 1e-9, p: 1e-12, f: 1e-15 };
function eng(text) {
  const m = String(text).trim().toLowerCase()
    .match(/^([+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?)\s*([a-z]*)$/);
  if (!m) return NaN;
  let scale = 1;
  if (m[2]) {
    for (const key of Object.keys(SUFFIX).sort((a, b) => b.length - a.length))
      if (m[2].startsWith(key)) { scale = SUFFIX[key]; break; }
  }
  return parseFloat(m[1]) * scale;
}
function fmt(v, digits = 4) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const a = Math.abs(v);
  if (a === 0) return "0";
  if (a >= 1e6 || a < 1e-3) return v.toExponential(digits - 1);
  return v.toPrecision(digits);
}
function siTime(v) {
  const a = Math.abs(v);
  if (a >= 1) return fmt(v) + " s";
  if (a >= 1e-3) return fmt(v * 1e3) + " ms";
  if (a >= 1e-6) return fmt(v * 1e6) + " µs";
  return fmt(v * 1e9) + " ns";
}
function siFreq(v) {
  if (v === null || v === undefined) return "—";
  if (v >= 1e6) return fmt(v / 1e6) + " MHz";
  if (v >= 1e3) return fmt(v / 1e3) + " kHz";
  return fmt(v) + " Hz";
}
function stat(label, value, unit) {
  return `<div class="stat"><div class="k">${label}</div>
    <div class="v">${value}${unit ? ` <small>${unit}</small>` : ""}</div></div>`;
}

/* ------------------------------------------------------------ canvas plots */
function setupCanvas(canvas) {
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#0e1626";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  return ctx;
}

function niceTicks(lo, hi, count) {
  const span = hi - lo || 1;
  const raw = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm >= 5 ? 5 : norm >= 2 ? 2 : 1) * mag;
  const ticks = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-12; v += step)
    ticks.push(v);
  return ticks;
}

function linePlot(canvas, xs, series, opts) {
  /* series: [{label, ys, color}], opts: {logX, yLabel, xLabel, symY} */
  const ctx = setupCanvas(canvas);
  const W = canvas.width, H = canvas.height;
  const padL = 78, padR = 18, padT = 18, padB = 42;
  const pw = W - padL - padR, ph = H - padT - padB;
  const tx = opts.logX ? (x) => Math.log10(Math.max(x, 1e-300)) : (x) => x;
  const xlo = tx(xs[0]), xhi = tx(xs[xs.length - 1]);
  let ylo = Infinity, yhi = -Infinity;
  for (const s of series) for (const y of s.ys) {
    if (y < ylo) ylo = y;
    if (y > yhi) yhi = y;
  }
  if (!isFinite(ylo)) { ylo = 0; yhi = 1; }
  if (yhi - ylo < 1e-12) { ylo -= 1; yhi += 1; }
  const margin = (yhi - ylo) * 0.08;
  ylo -= margin; yhi += margin;
  const X = (x) => padL + (tx(x) - xlo) / (xhi - xlo || 1) * pw;
  const Y = (y) => padT + (1 - (y - ylo) / (yhi - ylo)) * ph;

  ctx.strokeStyle = "#1e2a44"; ctx.fillStyle = "#8ea0bd";
  ctx.font = "12px Consolas, monospace"; ctx.lineWidth = 1;
  const yticks = niceTicks(ylo, yhi, 5);
  for (const t of yticks) {
    ctx.beginPath(); ctx.moveTo(padL, Y(t)); ctx.lineTo(W - padR, Y(t));
    ctx.stroke();
    ctx.textAlign = "right";
    ctx.fillText(fmt(t, 3), padL - 8, Y(t) + 4);
  }
  const xticks = opts.logX
    ? (() => { const out = [];
        for (let e = Math.ceil(xlo); e <= Math.floor(xhi); e++)
          out.push(Math.pow(10, e));
        return out; })()
    : niceTicks(xlo, xhi, 6);
  for (const t of xticks) {
    ctx.beginPath(); ctx.moveTo(X(t), padT); ctx.lineTo(X(t), H - padB);
    ctx.stroke();
    ctx.textAlign = "center";
    ctx.fillText(opts.xFmt ? opts.xFmt(t) : fmt(t, 3), X(t), H - padB + 18);
  }
  ctx.textAlign = "left";
  ctx.fillText(opts.yLabel || "", padL, 12);
  ctx.textAlign = "right";
  ctx.fillText(opts.xLabel || "", W - padR, H - 8);

  for (const s of series) {
    ctx.strokeStyle = s.color; ctx.lineWidth = 2;
    ctx.beginPath();
    let started = false;
    for (let i = 0; i < xs.length; i++) {
      const y = s.ys[i];
      if (!isFinite(y)) { started = false; continue; }
      const px = X(xs[i]), py = Y(Math.max(ylo, Math.min(yhi, y)));
      if (!started) { ctx.moveTo(px, py); started = true; }
      else ctx.lineTo(px, py);
    }
    ctx.stroke();
  }
}

function legend(el, series) {
  el.innerHTML = series.map((s) =>
    `<span class="item"><span class="swatch" style="background:${s.color}">
     </span>${s.label}</span>`).join("");
}

/* ---------------------------------------------------------------- tabs */
document.querySelectorAll("nav.tabs button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("nav.tabs button").forEach((b) =>
      b.classList.remove("active"));
    document.querySelectorAll(".tab").forEach((t) =>
      t.classList.remove("active"));
    btn.classList.add("active");
    $("tab-" + btn.dataset.tab).classList.add("active");
  });
});

/* ---------------------------------------------------------------- circuit */
$("load-example").addEventListener("click", () => {
  const key = $("example-select").value;
  if (EXAMPLES[key]) $("netlist").value = EXAMPLES[key];
});

$("run-parse").addEventListener("click", async () => {
  clearError("circuit-error");
  try {
    const data = await api("/api/parse", { netlist: $("netlist").value });
    $("parse-card").classList.remove("hidden");
    $("parse-summary").innerHTML =
      stat("元件", data.elements.length) +
      stat("节点", data.nodes.length) +
      stat("模型", Object.keys(data.models).length) +
      stat("分析", data.analyses.length);
    $("element-table").innerHTML =
      "<tr><th>名称</th><th>类型</th><th>节点</th><th>值 / 参数</th></tr>" +
      data.elements.map((el) => {
        let extra = el.value !== undefined ? fmt(el.value) :
          el.gain !== undefined ? "gain " + fmt(el.gain) :
          el.model ? el.model :
          el.dc !== undefined ? "DC " + fmt(el.dc) +
            (el.wave ? " + " + el.wave.kind : "") +
            (el.ac ? " · AC " + fmt(el.ac) : "") : "";
        return `<tr><td>${el.name}</td><td>${el.kind}</td>
          <td>${el.nodes.join(" ")}</td><td>${extra}</td></tr>`;
      }).join("");
    status("网表解析成功", "ok");
  } catch (err) { showError("circuit-error", err); status("解析失败", "err"); }
});

$("run-op").addEventListener("click", async () => {
  clearError("circuit-error");
  try {
    const data = await api("/api/op", { netlist: $("netlist").value });
    $("op-card").classList.remove("hidden");
    $("op-stats").innerHTML =
      stat("牛顿迭代", data.iterations) +
      stat("节点数", Object.keys(data.voltages).length);
    let rows = "<tr><th>未知量</th><th>值</th></tr>";
    for (const [k, v] of Object.entries(data.voltages))
      rows += `<tr><td>v(${k})</td><td>${fmt(v, 6)} V</td></tr>`;
    for (const [k, v] of Object.entries(data.currents))
      rows += `<tr><td>i(${k})</td><td>${fmt(v, 6)} A</td></tr>`;
    $("op-table").innerHTML = rows;
    status("工作点已求解", "ok");
  } catch (err) { showError("circuit-error", err); status("求解失败", "err"); }
});

/* ---------------------------------------------------------------- tran */
$("run-tran").addEventListener("click", async () => {
  clearError("tran-error");
  try {
    status("瞬态求解中…");
    const data = await api("/api/tran", {
      netlist: $("netlist").value,
      tstep: eng($("tran-step").value),
      tstop: eng($("tran-stop").value),
      method: $("tran-method").value,
    });
    const plot = data.plot;
    const series = Object.entries(plot.traces).map(([label, ys], i) =>
      ({ label, ys, color: COLORS[i % COLORS.length] }));
    linePlot($("wave-canvas"), plot.times, series,
      { yLabel: "V / A", xLabel: "t (s)", xFmt: siTime });
    legend($("wave-legend"), series);
    $("wave-summary-card").classList.remove("hidden");
    let rows = `<tr><th>迹线</th><th>min</th><th>max</th><th>终值</th>
      <th>上升时间</th><th>过冲 %</th><th>纹波 pp</th><th>频率</th></tr>`;
    for (const [label, s] of Object.entries(data.summary)) {
      rows += `<tr><td>${label}</td><td>${fmt(s.min)}</td>
        <td>${fmt(s.max)}</td><td>${fmt(s.final)}</td>
        <td>${s.rise_time !== null ? siTime(s.rise_time) : "—"}</td>
        <td>${fmt(s.overshoot_pct, 3)}</td><td>${fmt(s.ripple_pp)}</td>
        <td>${s.freq ? siFreq(s.freq) : "—"}</td></tr>`;
    }
    $("wave-table").innerHTML = rows;
    status(`瞬态完成 · ${data.times.length} 点 · ${data.retries} 次步长重试`, "ok");
  } catch (err) { showError("tran-error", err); status("瞬态失败", "err"); }
});

/* ---------------------------------------------------------------- ac */
$("run-ac").addEventListener("click", async () => {
  clearError("ac-error");
  try {
    status("AC 扫描中…");
    const data = await api("/api/ac", {
      netlist: $("netlist").value,
      mode: $("ac-mode").value,
      n: parseInt($("ac-n").value, 10),
      fstart: eng($("ac-start").value),
      fstop: eng($("ac-stop").value),
    });
    const labels = Object.keys(data.traces);
    const magSeries = labels.map((label, i) =>
      ({ label, ys: data.traces[label].db, color: COLORS[i % COLORS.length] }));
    const phSeries = labels.map((label, i) =>
      ({ label, ys: data.traces[label].phase, color: COLORS[i % COLORS.length] }));
    linePlot($("bode-mag"), data.freqs, magSeries,
      { logX: true, yLabel: "dB", xLabel: "f (Hz)", xFmt: siFreq });
    linePlot($("bode-phase"), data.freqs, phSeries,
      { logX: true, yLabel: "deg", xLabel: "f (Hz)", xFmt: siFreq });
    legend($("bode-legend"), magSeries);
    $("bode-summary-card").classList.remove("hidden");
    let rows = `<tr><th>迹线</th><th>低频增益</th><th>-3dB 带宽</th>
      <th>峰值</th><th>峰值频率</th></tr>`;
    for (const [label, s] of Object.entries(data.summary)) {
      rows += `<tr><td>${label}</td><td>${fmt(s.dc_gain_db)} dB</td>
        <td>${s.bandwidth ? siFreq(s.bandwidth) : "超出扫描"}</td>
        <td>${fmt(s.peak.db)} dB</td><td>${siFreq(s.peak.freq)}</td></tr>`;
    }
    $("bode-table").innerHTML = rows;
    status(`AC 完成 · ${data.freqs.length} 个频点`, "ok");
  } catch (err) { showError("ac-error", err); status("AC 失败", "err"); }
});

/* ---------------------------------------------------------------- matrix */
$("run-matrix").addEventListener("click", async () => {
  clearError("matrix-error");
  try {
    const data = await api("/api/matrix", {
      netlist: $("netlist").value, mode: $("matrix-mode").value,
    });
    $("matrix-stats").innerHTML =
      stat("矩阵规模", data.size + "×" + data.size) +
      stat("非零元", data.nonzeros) +
      stat("稠密度", (data.density * 100).toFixed(1), "%");
    const canvas = $("matrix-canvas");
    const n = data.size;
    const ctx = setupCanvas(canvas);
    const padL = 92, padT = 92, padR = 60;
    const cell = Math.min((canvas.width - padL - padR) / (n + 1),
                          (canvas.height - padT - 20) / n);
    ctx.font = "11px Consolas, monospace";
    for (let j = 0; j < n; j++) {
      ctx.save();
      ctx.translate(padL + j * cell + cell / 2, padT - 6);
      ctx.rotate(-Math.PI / 3);
      ctx.fillStyle = "#8ea0bd"; ctx.textAlign = "left";
      ctx.fillText(data.labels[j], 0, 0);
      ctx.restore();
    }
    for (let i = 0; i < n; i++) {
      ctx.fillStyle = "#8ea0bd"; ctx.textAlign = "right";
      ctx.fillText(data.labels[i], padL - 6, padT + i * cell + cell / 2 + 4);
      for (let j = 0; j < n; j++) {
        const level = data.cells[i][j];
        if (level > 0) {
          const g = Math.round(60 + 195 * Math.min(1, level));
          ctx.fillStyle = `rgb(${Math.round(20 + 25 * level)},${g},${Math.round(150 + 40 * level)})`;
        } else ctx.fillStyle = "#101a2e";
        ctx.fillRect(padL + j * cell, padT + i * cell,
                     Math.max(1, cell - 1), Math.max(1, cell - 1));
      }
      const rhsLevel = data.rhs[i] ? 1 : 0;
      ctx.fillStyle = rhsLevel ? "#fbbf24" : "#101a2e";
      ctx.fillRect(padL + n * cell + 6, padT + i * cell,
                   Math.max(1, cell - 1), Math.max(1, cell - 1));
    }
    ctx.fillStyle = "#fbbf24"; ctx.textAlign = "left";
    ctx.fillText("RHS", padL + n * cell + 4, padT - 6);
    status("MNA 矩阵已生成", "ok");
  } catch (err) { showError("matrix-error", err); status("矩阵失败", "err"); }
});

/* ---------------------------------------------------------------- newton */
$("run-newton").addEventListener("click", async () => {
  clearError("newton-error");
  try {
    const data = await api("/api/op", { netlist: $("netlist").value });
    const trace = data.trace;
    const xs = trace.map((s) => s.iter);
    const series = [
      { label: "max|Δv| (V)", ys: trace.map((s) => Math.max(s.dv, 1e-16)),
        color: COLORS[0] },
      { label: "max|Δi| (A)", ys: trace.map((s) => Math.max(s.di, 1e-16)),
        color: COLORS[1] },
    ];
    if (xs.length === 1) xs.push(2), series.forEach((s) => s.ys.push(s.ys[0]));
    /* log-scale y via log10 transform */
    const logSeries = series.map((s) =>
      ({ ...s, ys: s.ys.map((v) => Math.log10(v)) }));
    linePlot($("newton-canvas"), xs, logSeries,
      { yLabel: "log10", xLabel: "iteration", xFmt: (v) => String(Math.round(v)) });
    legend($("newton-legend"), series);
    let rows = "<tr><th>迭代</th><th>max|Δv|</th><th>max|Δi|</th></tr>";
    for (const s of trace)
      rows += `<tr><td>${s.iter}</td><td>${fmt(s.dv, 3)}</td>
        <td>${fmt(s.di, 3)}</td></tr>`;
    for (const [k, v] of Object.entries(data.voltages))
      rows += `<tr><td>v(${k})</td><td colspan="2">${fmt(v, 6)} V</td></tr>`;
    $("newton-table").innerHTML = rows;
    status(`牛顿收敛 · ${data.iterations} 次迭代`, "ok");
  } catch (err) { showError("newton-error", err); status("牛顿失败", "err"); }
});

/* ---------------------------------------------------------------- bench */
$("run-bench").addEventListener("click", async () => {
  try {
    status("基准运行中…");
    const data = await api("/api/bench", {
      stages: parseInt($("bench-stages").value, 10),
      points: parseInt($("bench-points").value, 10),
    });
    $("bench-stats").innerHTML =
      stat("矩阵", data.matrix_size + "×" + data.matrix_size) +
      stat("op", data.op_ms, "ms") +
      stat("tran", data.tran_ms_per_point, "ms/点") +
      stat("ac", data.ac_ms_per_point, "ms/频点");
    status("基准完成", "ok");
  } catch (err) { status("基准失败", "err"); alert(err.message); }
});

/* ---------------------------------------------------------------- init */
(async function init() {
  try {
    const res = await fetch("/api/info");
    const info = await res.json();
    EXAMPLES = info.examples || {};
    $("netlist").value = EXAMPLES.rc || "";
    $("footer-port").textContent =
      "port " + location.port + " · v" + info.version;
    status("已连接 · v" + info.version + " · 零依赖", "ok");
  } catch (err) {
    status("无法连接内核", "err");
  }
})();
