const BASE_URL = "http://127.0.0.1:8000";

const MODEL_LABELS = {
  distance_speed_baseline: "Baseline 1: Mesafe/Hız",
  historical_median_baseline: "Baseline 2: Tarihsel Medyan",
  xgboost: "XGBoost",
  catboost: "CatBoost (final model)",
};

const MODEL_COLORS = {
  distance_speed_baseline: "#95a5a6",
  historical_median_baseline: "#e67e22",
  xgboost: "#3498db",
  catboost: "#2ecc71",
};

const ACCURACY_COLORS = ["#2ecc71", "#82c91e", "#f1c40f", "#e74c3c"];
const IMPORTANCE_PALETTE = ["#2ecc71", "#3498db", "#9b59b6", "#e67e22", "#f1c40f", "#95a5a6"];

const content = document.getElementById("content");

async function getJson(path) {
  const res = await fetch(`${BASE_URL}${path}`);
  if (!res.ok) throw new Error(`${path} -> HTTP ${res.status}`);
  return res.json();
}

function fmt(v, digits = 2) {
  return v == null ? "—" : v.toFixed(digits);
}

// ---------- SVG grafik yardımcıları (harici kütüphane yok - proje minimal
// bağımlılık tercihiyle tutarlı, tek seferlik kullanılan küçük yardımcılar) ----------

/** items: [{label, value, n?}]. colorFn(item,i) -> hex renk. */
function svgBarChart(items, { colorFn = () => "#3498db", valueFmt = (v) => v.toFixed(2), width = 600 } = {}) {
  if (items.length === 0) return "";
  const barHeight = 24;
  const gap = 10;
  const labelW = 150;
  const valueW = 70;
  const barAreaW = width - labelW - valueW;
  const max = Math.max(...items.map((i) => i.value), 0.001);
  const height = items.length * (barHeight + gap) + gap;

  const bars = items
    .map((item, i) => {
      const y = gap + i * (barHeight + gap);
      const w = Math.max((item.value / max) * barAreaW, 2);
      const color = colorFn(item, i);
      const nSuffix = item.n != null ? ` (n=${item.n})` : "";
      return `
        <text x="${labelW - 8}" y="${y + barHeight / 2 + 4}" text-anchor="end" font-size="12" fill="#444">${item.label}</text>
        <rect x="${labelW}" y="${y}" width="${barAreaW}" height="${barHeight}" rx="5" fill="#eef0f3"></rect>
        <rect x="${labelW}" y="${y}" width="${w}" height="${barHeight}" rx="5" fill="${color}">
          <title>${item.label}${nSuffix}: ${valueFmt(item.value)}</title>
        </rect>
        <text x="${labelW + w + 8}" y="${y + barHeight / 2 + 4}" font-size="12" fill="#333" font-weight="600">${valueFmt(item.value)}</text>
      `;
    })
    .join("");

  return `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img">${bars}</svg>`;
}

/** segments: [{label, value, color}]. Ortasi bos donut (pasta) grafik. */
function svgDonutChart(segments, { size = 170, thickness = 30 } = {}) {
  const total = segments.reduce((s, x) => s + x.value, 0) || 1;
  const r = size / 2;
  const rInner = r - thickness;
  const cx = r;
  const cy = r;
  let angle = -Math.PI / 2;

  const paths = segments
    .filter((seg) => seg.value > 0)
    .map((seg) => {
      const frac = seg.value / total;
      const startAngle = angle;
      const endAngle = angle + frac * Math.PI * 2;
      angle = endAngle;
      const large = endAngle - startAngle > Math.PI ? 1 : 0;
      const x1 = cx + r * Math.cos(startAngle);
      const y1 = cy + r * Math.sin(startAngle);
      const x2 = cx + r * Math.cos(endAngle);
      const y2 = cy + r * Math.sin(endAngle);
      const ix1 = cx + rInner * Math.cos(endAngle);
      const iy1 = cy + rInner * Math.sin(endAngle);
      const ix2 = cx + rInner * Math.cos(startAngle);
      const iy2 = cy + rInner * Math.sin(startAngle);
      const d = `M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} L ${ix1} ${iy1} A ${rInner} ${rInner} 0 ${large} 0 ${ix2} ${iy2} Z`;
      const pct = ((seg.value / total) * 100).toFixed(1);
      return `<path d="${d}" fill="${seg.color}"><title>${seg.label}: ${pct}%</title></path>`;
    })
    .join("");

  return `<svg class="donut" viewBox="0 0 ${size} ${size}" role="img">${paths}</svg>`;
}

/** points: [{actual_min, predicted_min}, ...]. Tahmin vs gercek scatter -
 * kirisik cizgi (y=x, mukemmel tahmin) etrafinda ne kadar dagildigini,
 * modelin KISA ETA'larda mi UZUN ETA'larda mi daha kotu oldugunu tek
 * bakista gosterir (noktalar cizginin UZERINDEyse fazla tahmin, ALTINDAysa
 * eksik tahmin ediyor demektir). */
function svgScatterChart(points, { width = 480, height = 360 } = {}) {
  if (points.length === 0) return "<p class='hint'>Örnek yok.</p>";
  const pad = 36;
  const maxVal = Math.max(...points.map((p) => Math.max(p.actual_min, p.predicted_min)), 1) * 1.05;

  const toX = (v) => pad + (v / maxVal) * (width - pad * 1.5);
  const toY = (v) => height - pad - (v / maxVal) * (height - pad * 1.5);

  const dots = points
    .map((p) => `<circle cx="${toX(p.actual_min).toFixed(1)}" cy="${toY(p.predicted_min).toFixed(1)}" r="2.6" fill="#2c6ecb" fill-opacity="0.35" />`)
    .join("");

  const diagEnd = toX(maxVal);
  const axisTicks = [0, maxVal / 4, maxVal / 2, (maxVal * 3) / 4, maxVal]
    .map((v) => v.toFixed(0))
    .filter((v, i, arr) => arr.indexOf(v) === i);

  const xTicks = axisTicks
    .map((t) => `<text x="${toX(+t)}" y="${height - pad + 16}" font-size="10" fill="#999" text-anchor="middle">${t}</text>`)
    .join("");
  const yTicks = axisTicks
    .map((t) => `<text x="${pad - 8}" y="${toY(+t) + 3}" font-size="10" fill="#999" text-anchor="end">${t}</text>`)
    .join("");

  return `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img">
    <line x1="${pad}" y1="${height - pad}" x2="${diagEnd}" y2="${pad}" stroke="#ccd1d9" stroke-width="1.5" stroke-dasharray="4 3" />
    <line x1="${pad}" y1="${height - pad}" x2="${width - pad / 2}" y2="${height - pad}" stroke="#ddd" stroke-width="1" />
    <line x1="${pad}" y1="${pad / 2}" x2="${pad}" y2="${height - pad}" stroke="#ddd" stroke-width="1" />
    ${dots}
    ${xTicks}
    ${yTicks}
    <text x="${width / 2}" y="${height - 4}" font-size="11" fill="#666" text-anchor="middle">Gerçek ETA (dk)</text>
    <text x="12" y="${height / 2}" font-size="11" fill="#666" text-anchor="middle" transform="rotate(-90 12 ${height / 2})">Tahmin (dk)</text>
  </svg>`;
}

function donutLegend(segments) {
  const total = segments.reduce((s, x) => s + x.value, 0) || 1;
  return `<ul class="donut-legend">${segments
    .map(
      (seg) => `<li>
        <span class="dot" style="background:${seg.color}"></span>
        <span class="legend-label">${seg.label}</span>
        <span class="legend-value">${((seg.value / total) * 100).toFixed(1)}%</span>
      </li>`
    )
    .join("")}</ul>`;
}

/** MAE degerine gore yesil (dusuk hata) -> kirmizi (yuksek hata) renk skalasi -
 * kirilim grafiklerinde hangi grubun daha iyi/kotu performans gosterdigini
 * bir bakista gostermek icin. */
function heatColorScale(items) {
  const values = items.map((i) => i.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  return (item) => {
    const t = max > min ? (item.value - min) / (max - min) : 0;
    const hue = 120 - 120 * t; // 120=yesil, 0=kirmizi
    return `hsl(${hue.toFixed(0)}, 65%, 48%)`;
  };
}

function kpiCard(label, value, sub, accent = "#2ecc71") {
  return `<div class="kpi-card" style="border-left-color:${accent}">
    <div class="kpi-value">${value}</div>
    <div class="kpi-label">${label}</div>
    ${sub ? `<div class="kpi-sub">${sub}</div>` : ""}
  </div>`;
}

function comparisonTable(comparison, selected) {
  const rows = Object.entries(comparison)
    .map(([key, m]) => {
      const cls = key === selected ? ' class="highlight"' : "";
      return `<tr${cls}>
        <td>${MODEL_LABELS[key] ?? key}</td>
        <td>${fmt(m.mae_min)}</td>
        <td>${fmt(m.rmse_min)}</td>
        <td>${fmt(m.median_ae_min)}</td>
        <td>${fmt(m.within_1min_pct, 1)}%</td>
        <td>${fmt(m.within_2min_pct, 1)}%</td>
        <td>${fmt(m.within_3min_pct, 1)}%</td>
        <td>${m.n}</td>
      </tr>`;
    })
    .join("");

  return `<table>
    <thead><tr>
      <th>Model</th><th>MAE (dk)</th><th>RMSE (dk)</th><th>MedAE (dk)</th>
      <th>±1dk</th><th>±2dk</th><th>±3dk</th><th>n</th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function comparisonBarChart(comparison) {
  const items = Object.entries(comparison).map(([key, m]) => ({
    label: MODEL_LABELS[key] ?? key,
    value: m.mae_min ?? 0,
    n: m.n,
    key,
  }));
  return svgBarChart(items, {
    colorFn: (item) => MODEL_COLORS[item.key] ?? "#3498db",
    valueFmt: (v) => `${v.toFixed(2)} dk`,
  });
}

function breakdownCard(title, breakdown) {
  const entries = Object.entries(breakdown);
  if (entries.length === 0) return "";
  const items = entries.map(([key, m]) => ({ label: key, value: m.mae_min ?? 0, n: m.n }));
  const chart = svgBarChart(items, {
    colorFn: heatColorScale(items),
    valueFmt: (v) => `${v.toFixed(2)} dk`,
    width: 420,
  });
  const rows = entries
    .map(
      ([key, m]) => `<tr>
      <td>${key}</td>
      <td>${fmt(m.mae_min)}</td>
      <td>${fmt(m.rmse_min)}</td>
      <td>${fmt(m.within_2min_pct, 1)}%</td>
      <td>${m.n}</td>
    </tr>`
    )
    .join("");

  return `<div class="card">
    <h3>${title}</h3>
    <p class="chart-caption">MAE (dakika) — yeşil düşük hata, kırmızı yüksek hata</p>
    ${chart}
    <details>
      <summary>Tam tablo</summary>
      <table>
        <thead><tr><th>Grup</th><th>MAE (dk)</th><th>RMSE (dk)</th><th>±2dk</th><th>n</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </details>
  </div>`;
}

function importanceBars(importance) {
  const entries = Object.entries(importance);
  const max = Math.max(...entries.map(([, v]) => v), 0.001);
  return `<div class="bars">${entries
    .map(
      ([feat, val]) => `<div class="bar-row">
        <span>${feat}</span>
        <span class="bar-track"><span class="bar-fill" style="width:${(val / max) * 100}%"></span></span>
        <span class="bar-value">${val.toFixed(3)} dk</span>
      </div>`
    )
    .join("")}</div>`;
}

/** SHAP onem degerlerinin toplam etki icindeki PAYINI (yuzde) gosteren
 * donut - "hangi feature'lar ETA'yi ne kadar etkiliyor" sorusuna tek
 * bakista cevap verir. Ilk 5 feature + geri kalani "Diğer". */
function importanceDonutSection(importance, title) {
  const entries = Object.entries(importance);
  const top = entries.slice(0, 5);
  const restSum = entries.slice(5).reduce((s, [, v]) => s + v, 0);
  const segments = top.map(([feat, val], i) => ({
    label: feat,
    value: val,
    color: IMPORTANCE_PALETTE[i % IMPORTANCE_PALETTE.length],
  }));
  if (restSum > 0) segments.push({ label: "Diğer", value: restSum, color: "#ccd1d9" });

  return `<div class="donut-block">
    <h4>${title}</h4>
    <div class="donut-row">
      ${svgDonutChart(segments)}
      ${donutLegend(segments)}
    </div>
  </div>`;
}

function verdictText(comparison) {
  const cat = comparison.catboost;
  const xgb = comparison.xgboost;
  const b1 = comparison.distance_speed_baseline;
  const b2 = comparison.historical_median_baseline;

  const beatsBaselines = cat.mae_min < b1.mae_min && cat.mae_min < b2.mae_min;
  const cls = beatsBaselines ? "verdict" : "verdict warn";
  const icon = beatsBaselines ? "✅" : "⚠️";

  return `<div class="${cls}">
    <strong>${icon} Seçilen model: CatBoost.</strong>
    Test setinde MAE=${fmt(cat.mae_min)}dk, RMSE=${fmt(cat.rmse_min)}dk, ±2dk doğruluk=${fmt(cat.within_2min_pct, 1)}%.
    XGBoost'u (MAE=${fmt(xgb.mae_min)}dk) ve her iki baseline'ı da
    (Mesafe/Hız MAE=${fmt(b1.mae_min)}dk, Tarihsel Medyan MAE=${fmt(b2.mae_min)}dk) geçiyor.
    ${beatsBaselines ? "" : " UYARI: model baseline'ların en az birini geçemiyor — bu sonuç dürüstçe raporlanmalı."}
    Detaylı gerekçe için <code>docs/faz3-final-raporu.md</code>'a bakınız.
  </div>`;
}

function accuracyDonutSection(cat) {
  const p1 = cat.within_1min_pct ?? 0;
  const p2 = Math.max((cat.within_2min_pct ?? 0) - p1, 0);
  const p3 = Math.max((cat.within_3min_pct ?? 0) - p1 - p2, 0);
  const p4 = Math.max(100 - p1 - p2 - p3, 0);
  const segments = [
    { label: "≤1 dk hata", value: p1, color: ACCURACY_COLORS[0] },
    { label: "1–2 dk hata", value: p2, color: ACCURACY_COLORS[1] },
    { label: "2–3 dk hata", value: p3, color: ACCURACY_COLORS[2] },
    { label: "3dk+ hata", value: p4, color: ACCURACY_COLORS[3] },
  ];
  return `<div class="donut-row">
    ${svgDonutChart(segments, { size: 190, thickness: 34 })}
    ${donutLegend(segments)}
  </div>`;
}

/** livePerf: /api/model/live-performance cevabi. testMae: dondurulmus test
 * setinin (metrics.comparison.catboost) MAE'si - out-of-sample sonucun
 * "orijinal test setine gore ne kadar farkli" oldugunu gostermek icin. */
function livePerformanceSection(livePerf, testMae) {
  if (!livePerf || livePerf.n === 0) {
    return `<div class="card"><p class="hint">${livePerf?.message ?? "Henüz canlı (out-of-sample) veri yok."}</p></div>`;
  }
  const m = livePerf.metrics;
  const delta = m.mae_min - testMae;
  const worse = delta > 0.15; // dondurulmus test setinden belirgin sekilde daha kotu
  const from = new Date(livePerf.date_range.from).toLocaleDateString("tr-TR");
  const to = new Date(livePerf.date_range.to).toLocaleDateString("tr-TR");

  const kpis = `
    <section class="kpi-row" style="margin-bottom:16px;">
      ${kpiCard("Out-of-sample MAE", `${fmt(m.mae_min)} dk`, `n=${livePerf.n}`, worse ? "#e67e22" : "#2ecc71")}
      ${kpiCard("±2 Dakika Doğruluk", `${fmt(m.within_2min_pct, 1)}%`, "canlı veri", "#3498db")}
      ${kpiCard("Dondurulmuş Test MAE'ye Fark", `${delta >= 0 ? "+" : ""}${fmt(delta)} dk`, worse ? "daha kötü" : "yakın/daha iyi", worse ? "#e74c3c" : "#2ecc71")}
    </section>`;

  const lineBreakdown = breakdownCard("Hat bazında (out-of-sample)", livePerf.breakdowns.by_line_no);
  const etaBreakdown = breakdownCard("ETA aralığı bazında (out-of-sample)", livePerf.breakdowns.by_eta_range);

  return `
    <p class="hint">${from} – ${to} arası toplanan, modelin train/validation/test aşamalarının HİÇBİRİNDE görmediği ${livePerf.n} satır üzerinde hesaplandı.</p>
    ${kpis}
    <div class="${worse ? "verdict warn" : "verdict"}" style="margin-bottom:20px;">
      ${worse ? "⚠️" : "✅"} ${livePerf.note}
      ${worse ? " Fark dikkat çekici büyüklükte — modelin zaman içinde/farklı koşullarda dondurulmuş test setinden daha zayıf performans gösterebileceğine işaret ediyor, bu dürüstçe raporlanmalı." : ""}
    </div>
    <div class="grid-2">${lineBreakdown}${etaBreakdown}</div>
  `;
}

async function init() {
  try {
    const [metrics, importance, livePerf] = await Promise.all([
      getJson("/api/model/metrics"),
      getJson("/api/model/feature-importance"),
      getJson("/api/model/live-performance").catch((err) => ({ n: 0, message: `Yüklenemedi: ${err.message}` })),
    ]);

    const cat = metrics.comparison.catboost;

    content.innerHTML = `
      <section class="kpi-row">
        ${kpiCard("Ortalama Hata (MAE)", `${fmt(cat.mae_min)} dk`, "CatBoost, test seti", "#2ecc71")}
        ${kpiCard("±2 Dakika Doğruluk", `${fmt(cat.within_2min_pct, 1)}%`, "tahminlerin yüzdesi", "#3498db")}
        ${kpiCard("RMSE", `${fmt(cat.rmse_min)} dk`, "büyük hatalara duyarlı", "#9b59b6")}
        ${kpiCard("Test Örneklem", `${metrics.test_n}`, `train ${metrics.train_n} · val ${metrics.validation_n}`, "#e67e22")}
      </section>

      <section>
        <h2>Model Karşılaştırması (Test Seti)</h2>
        <p class="hint">Train: ${metrics.train_n} · Validation: ${metrics.validation_n} · Test: ${metrics.test_n} satır (event-bazlı + zamansal split)</p>
        <div class="card">
          <p class="chart-caption">Ortalama Mutlak Hata (MAE) — düşük daha iyi</p>
          ${comparisonBarChart(metrics.comparison)}
        </div>
        <details class="table-details">
          <summary>Tam karşılaştırma tablosu</summary>
          ${comparisonTable(metrics.comparison, metrics.selected_model)}
        </details>
      </section>

      <section>
        <h2>Model Seçimi Gerekçesi</h2>
        ${verdictText(metrics.comparison)}
      </section>

      <section>
        <h2>CatBoost Doğruluk Dağılımı (Test Seti)</h2>
        <div class="card">${accuracyDonutSection(cat)}</div>
      </section>

      <section>
        <h2>Tahmin vs Gerçek (Test Seti)</h2>
        <p class="hint">Her nokta bir tahmin — kesikli çizgi mükemmel tahmini temsil eder. Çizginin üzerindeki noktalar fazla tahmin, altındakiler eksik tahmin edilmiş demektir.</p>
        <div class="card">${svgScatterChart(metrics.scatter_sample_catboost ?? [])}</div>
      </section>

      <section>
        <h2>Gerçek Zamanlı (Out-of-Sample) Model Performansı</h2>
        ${livePerformanceSection(livePerf, cat.mae_min)}
      </section>

      <section>
        <h2>CatBoost Kırılımları (Test Seti)</h2>
        <div class="grid-2">
          ${breakdownCard("Hat bazında", metrics.breakdowns_catboost.by_line_no)}
          ${breakdownCard("Yön bazında", metrics.breakdowns_catboost.by_direction)}
          ${breakdownCard("ETA aralığı bazında", metrics.breakdowns_catboost.by_eta_range)}
          ${breakdownCard("Label kalitesi bazında", metrics.breakdowns_catboost.by_label_quality)}
        </div>
      </section>

      <section>
        <h2>Feature Importance — SHAP (ortalama |etki|, dakika)</h2>
        <p class="hint">Test seti üzerinde hesaplandı (${importance.test_n} satır) — train üzerinde değil, overfit edilmiş ilişkileri yansıtmaması için.</p>
        <div class="grid-2">
          ${importanceDonutSection(importance.catboost_mean_abs_shap_min, "CatBoost — etki payı")}
          ${importanceDonutSection(importance.xgboost_mean_abs_shap_min, "XGBoost — etki payı")}
        </div>
        <div class="grid-2" style="margin-top:20px;">
          <div class="card">
            <h3 style="font-size:13px;color:#666;">XGBoost</h3>
            ${importanceBars(importance.xgboost_mean_abs_shap_min)}
          </div>
          <div class="card">
            <h3 style="font-size:13px;color:#666;">CatBoost (final model)</h3>
            ${importanceBars(importance.catboost_mean_abs_shap_min)}
          </div>
        </div>
      </section>
    `;
  } catch (err) {
    content.innerHTML = `<p id="error">Yükleme hatası: ${err.message} (backend çalışıyor mu? uvicorn app.api.main:app --port 8000)</p>`;
  }
}

init();
