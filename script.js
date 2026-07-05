const $ = (id) => document.getElementById(id);

const state = {
    meta: null,
    paused: false,
    sat: null,
    drone: null,
    satHistory: [],
    droneHistory: [],
    activePage: 'sat',
    failureCount: 0,
};

const KYIV = {lat: 50.45, lon: 30.52};

// Earth photo (equirectangular / "flat world map" projection, 2:1 aspect ratio works best)
const earthImg = new Image();
let earthImgLoaded = false;
earthImg.onload = () => {
    earthImgLoaded = true;
};
earthImg.onerror = () => {
    earthImgLoaded = false;
};
earthImg.src = 'Earth.jpg';

const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const lerp = (a, b, t) => a + (b - a) * t;
const fmt = (v, d = 1, suffix = '') => (Number.isFinite(Number(v)) ? `${Number(v).toFixed(d)}${suffix}` : '--');
const fmtInt = (v, suffix = '') => (Number.isFinite(Number(v)) ? `${Math.round(Number(v)).toLocaleString('uk-UA')}${suffix}` : '--');
const rad = (deg) => deg * Math.PI / 180;

function setText(id, value) {
    const el = $(id);
    if (el) el.textContent = value;
}

async function apiGet(url) {
    const res = await fetch(url, {cache: 'no-store'});
    if (!res.ok) throw new Error(`${url}: ${res.status}`);
    return res.json();
}

async function apiPost(url, body = {}) {
    const res = await fetch(url, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`${url}: ${res.status}`);
    return res.json();
}

function nowTime() {
    return new Date().toISOString().slice(11, 19);
}

function formatDuration(seconds) {
    seconds = Math.max(0, Math.floor(Number(seconds) || 0));
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function statusClass(status) {
    const s = String(status || '').toUpperCase();
    if (['DANGER', 'CRITICAL'].includes(s)) return 'danger';
    if (['CAUTION', 'ALERT', 'WATCH'].includes(s)) return 'caution';
    return '';
}

function statusUa(status) {
    const s = String(status || '').toUpperCase();
    if (s === 'DANGER' || s === 'CRITICAL') return 'КРИТИЧНИЙ';
    if (s === 'CAUTION' || s === 'ALERT') return 'УВАГА';
    if (s === 'WATCH') return 'WATCH';
    if (s === 'SAFE') return 'SAFE';
    return s || '--';
}

function solarActivityLabel(kp) {
    const v = Number(kp);
    if (!Number.isFinite(v)) return '--';
    if (v < 4) return 'СПОКІЙНО';
    if (v < 5) return 'ПІДВИЩЕНА';
    if (v < 7) return 'ШТОРМ';
    return 'СИЛЬНИЙ ШТОРМ';
}

function prepareCanvas(canvas) {
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const width = Math.max(10, Math.floor(rect.width));
    const height = Math.max(10, Math.floor(rect.height));
    if (canvas.width !== width * dpr || canvas.height !== height * dpr) {
        canvas.width = width * dpr;
        canvas.height = height * dpr;
    }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return {ctx, width, height};
}

function drawSparkline(id, values, options = {}) {
    const canvas = $(id);
    const prepared = prepareCanvas(canvas);
    if (!prepared) return;
    const {ctx, width, height} = prepared;
    ctx.clearRect(0, 0, width, height);

    const clean = values.filter((v) => Number.isFinite(Number(v))).map(Number);
    if (clean.length < 2) return;

    let min = options.min ?? Math.min(...clean);
    let max = options.max ?? Math.max(...clean);
    if (Math.abs(max - min) < 0.0001) {
        max += 1;
        min -= 1;
    }
    if (options.min === undefined && options.max === undefined) {
        const pad = (max - min) * 0.12;
        min -= pad;
        max += pad;
    }

    ctx.strokeStyle = 'rgba(80, 220, 255, .12)';
    ctx.lineWidth = 1;
    for (let i = 1; i < 4; i++) {
        const y = (height / 4) * i;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
    }

    const color = options.color || 'cyan';
    const palettes = {
        cyan: ['rgba(34,211,238,.92)', 'rgba(0,255,136,.85)'],
        orange: ['rgba(251,146,60,.92)', 'rgba(247,201,72,.85)'],
        red: ['rgba(255,49,88,.95)', 'rgba(251,146,60,.85)'],
        purple: ['rgba(192,132,252,.94)', 'rgba(56,189,248,.78)'],
        green: ['rgba(0,255,136,.94)', 'rgba(34,211,238,.75)'],
        blue: ['rgba(56,189,248,.92)', 'rgba(34,211,238,.78)'],
    };
    const p = palettes[color] || palettes.cyan;
    const grad = ctx.createLinearGradient(0, 0, width, 0);
    grad.addColorStop(0, p[0]);
    grad.addColorStop(1, p[1]);

    const points = clean.map((v, i) => ({
        x: (i / (clean.length - 1)) * width,
        y: height - ((v - min) / (max - min)) * height,
    }));

    ctx.beginPath();
    points.forEach((pt, i) => i ? ctx.lineTo(pt.x, pt.y) : ctx.moveTo(pt.x, pt.y));
    ctx.strokeStyle = grad;
    ctx.lineWidth = options.thin ? 1.3 : 2;
    ctx.stroke();

    if (!options.noFill) {
        ctx.lineTo(width, height);
        ctx.lineTo(0, height);
        ctx.closePath();
        const fill = ctx.createLinearGradient(0, 0, 0, height);
        fill.addColorStop(0, p[0].replace('.92', '.16').replace('.94', '.16').replace('.95', '.16'));
        fill.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = fill;
        ctx.fill();
    }
}

// Приладова шкала (як стрічка швидкості/висоти в реальних приладах) замість лінійного графіка.
// Показує поточне значення як позицію повзунка на шкалі мін→макс, з підписами меж.
function drawScaleGauge(id, value, min, max, options = {}) {
    const canvas = $(id);
    const prepared = prepareCanvas(canvas);
    if (!prepared) return;
    const {ctx, width, height} = prepared;
    ctx.clearRect(0, 0, width, height);
    if (!Number.isFinite(Number(value))) return;

    const colorMap = {
        cyan: '#22d3ee', blue: '#38bdf8', green: '#00ff88',
        orange: '#fb923c', red: '#ff3158', purple: '#c084fc', yellow: '#f7c948',
    };
    const color = colorMap[options.color] || colorMap.cyan;
    const v = clamp(Number(value), min, max);

    const padX = 6;
    const trackY = height * 0.38;
    const left = padX, right = width - padX, trackW = right - left;

    // базова лінія шкали
    ctx.strokeStyle = 'rgba(140,170,205,.30)';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(left, trackY);
    ctx.lineTo(right, trackY);
    ctx.stroke();

    // поділки
    const ticks = options.ticks || 6;
    ctx.strokeStyle = 'rgba(140,170,205,.45)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= ticks; i++) {
        const x = left + trackW * (i / ticks);
        const h = (i === 0 || i === ticks) ? 7 : (i === ticks / 2 ? 6 : 4);
        ctx.beginPath();
        ctx.moveTo(x, trackY - h / 2);
        ctx.lineTo(x, trackY + h / 2);
        ctx.stroke();
    }

    // заповнена частина до поточного значення
    const pct = max > min ? (v - min) / (max - min) : 0;
    const px = left + trackW * clamp(pct, 0, 1);
    ctx.strokeStyle = color;
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(left, trackY);
    ctx.lineTo(px, trackY);
    ctx.stroke();

    // повзунок-покажчик
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(px, trackY - 8);
    ctx.lineTo(px - 5, trackY - 1);
    ctx.lineTo(px + 5, trackY - 1);
    ctx.closePath();
    ctx.fill();
    ctx.beginPath();
    ctx.arc(px, trackY + 4, 2.4, 0, Math.PI * 2);
    ctx.fill();

    // підписи меж шкали
    ctx.font = "9.5px 'Share Tech Mono'";
    ctx.fillStyle = 'rgba(170,195,225,.9)';
    ctx.textAlign = 'left';
    ctx.fillText(options.minLabel ?? String(Math.round(min)), left, height - 2);
    ctx.textAlign = 'right';
    ctx.fillText(options.maxLabel ?? String(Math.round(max)), right, height - 2);
}

function setBars(id, pct) {
    const el = $(id);
    if (!el) return;
    const n = 7;
    const active = Math.round(clamp(pct, 0, 100) / 100 * n);
    el.innerHTML = Array.from({length: n}, (_, i) => `<span class="${i < active ? 'on' : ''}"></span>`).join('');
}

function setProgress(id, pct) {
    const el = $(id);
    if (el) el.style.width = `${clamp(pct, 0, 100)}%`;
}

function populateScenarios(meta) {
    const satSelect = $('satScenarioSelect');
    const satButtons = $('satScenarioButtons');
    satSelect.innerHTML = '';
    satButtons.innerHTML = '';

    meta.satellite_scenarios.forEach((s) => {
        const opt = document.createElement('option');
        opt.value = s.key;
        opt.textContent = `${s.key.toUpperCase()} — ${s.title}`;
        satSelect.appendChild(opt);

        const btn = document.createElement('button');
        btn.className = 'scenario-btn';
        btn.dataset.key = s.key;
        btn.textContent = scenarioLabel(s.key);
        btn.addEventListener('click', async () => {
            await apiPost('/api/satellite/scenario', {key: s.key});
            satSelect.value = s.key;
            await updateTelemetry();
        });
        satButtons.appendChild(btn);
    });

    satSelect.addEventListener('change', async () => {
        await apiPost('/api/satellite/scenario', {key: satSelect.value});
        await updateTelemetry();
    });

    const drSelect = $('droneScenarioSelect');
    const drButtons = $('droneScenarioButtons');
    drSelect.innerHTML = '';
    drButtons.innerHTML = '';
    meta.drone_scenarios.forEach((name) => {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        drSelect.appendChild(opt);

        const btn = document.createElement('button');
        btn.className = 'scenario-btn';
        btn.dataset.name = name;
        btn.textContent = name;
        btn.addEventListener('click', async () => {
            await apiPost('/api/drone/scenario', {name});
            drSelect.value = name;
            await updateTelemetry();
        });
        drButtons.appendChild(btn);
    });

    drSelect.addEventListener('change', async () => {
        await apiPost('/api/drone/scenario', {name: drSelect.value});
        await updateTelemetry();
    });
}

function scenarioLabel(key) {
    const labels = {
        normal: 'Normal mission',
        geomagnetic: 'Geomagnetic storm',
        solar_flare: 'Solar flare',
        drag: 'Drag increase',
        blackout: 'Blackout',
        debris: 'Debris avoidance',
        eclipse: 'Eclipse',
        thermal: 'Thermal anomaly',
    };
    return labels[key] || key;
}

function markActiveScenarios(sat, drone) {
    document.querySelectorAll('#satScenarioButtons .scenario-btn').forEach((btn) => btn.classList.toggle('active', btn.dataset.key === sat.scenario));
    document.querySelectorAll('#droneScenarioButtons .scenario-btn').forEach((btn) => btn.classList.toggle('active', btn.dataset.name === drone.scenario));
    if ($('satScenarioSelect')) $('satScenarioSelect').value = sat.scenario;
    if ($('droneScenarioSelect')) $('droneScenarioSelect').value = drone.scenario;
}

function attachUi() {
    document.querySelectorAll('.tab').forEach((tab) => {
        tab.addEventListener('click', () => {
            const page = tab.dataset.page;
            state.activePage = page;
            document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t === tab));
            document.querySelectorAll('.page').forEach((p) => p.classList.toggle('active', p.id === `page-${page}`));
            redrawAll();
        });
    });

    document.querySelectorAll('#pauseBtn').forEach((btn) => {
        btn.addEventListener('click', async () => {
            await apiPost('/api/control/toggle');
            await updateTelemetry();
        });
    });
    document.querySelectorAll('#resetBtn').forEach((btn) => {
        btn.addEventListener('click', async () => {
            await apiPost('/api/control/reset');
            await updateTelemetry();
        });
    });

    window.addEventListener('keydown', async (event) => {
        if (event.code === 'Space') {
            event.preventDefault();
            await apiPost('/api/control/toggle');
            await updateTelemetry();
        }
        if (event.key.toLowerCase() === 'r') {
            await apiPost('/api/control/reset');
            await updateTelemetry();
        }
    });

    window.addEventListener('resize', redrawAll);
}

function updateSatellite(sat, history) {
    setText('satMapTime', sat.utc_time || '-- UTC');
    setText('utcClock', `UTC ${String(sat.utc_time || new Date().toISOString()).slice(11, 19)}`);
    setText('satScenarioName', scenarioLabel(sat.scenario));
    setText('satLat', `${fmt(Math.abs(sat.latitude_deg), 2, '°')} ${sat.latitude_deg >= 0 ? 'N' : 'S'}`);
    setText('satLon', `${fmt(Math.abs(sat.longitude_deg), 2, '°')} ${sat.longitude_deg >= 0 ? 'E' : 'W'}`);
    setText('satAlt', fmt(sat.altitude_km, 1, ' км'));
    setText('satVel', fmtInt(sat.velocity_kmh, ' км/год'));
    setText('satBatt', fmt(sat.battery_soc_pct, 1, '%'));
    setText('satVis', sat.visibility === 'daylight' ? 'ДЕНЬ' : 'ТІНЬ ЗЕМЛІ');
    setText('satRad', fmt(sat.radiation_index, 1, ' μRad/h'));
    setText('satComm', fmt(sat.comm_quality_pct, 1, '%'));
    setText('satStripLat', fmt(sat.latitude_deg, 2, '°'));
    setText('satStripLon', fmt(sat.longitude_deg, 2, '°'));
    setText('satStripAlt', fmt(sat.altitude_km, 1, ' км'));
    setText('satStripVel', fmtInt(sat.velocity_kmh, ' км/год'));
    setText('satPeriod', fmt(sat.orbital_period_min, 1, ' хв'));
    setText('satPhase', sat.visibility === 'daylight' ? 'СОНЦЕ' : 'ECLIPSE');
    setText('missionScore', fmt(sat.mission_score, 0, '%'));
    setText('satStatusBadge', sat.system_status || '--');
    setText('cabinTemp', fmt(sat.cabin_temp_c, 1, ' °C'));
    setText('cabinHum', fmt(sat.cabin_humidity_pct, 1, ' %'));
    setText('cabinPress', fmt(sat.cabin_pressure_psi, 2, ' PSI'));
    setText('co2Level', fmt(sat.co2_mmhg * 170, 0, ' ppm'));
    setText('attErr', fmt(sat.attitude_error_deg, 3, '°'));
    setText('deltaV', fmt(sat.delta_v_ms, 3, ' м/с'));
    setText('statusText', statusUa(sat.system_status));
    setText('kpValue', `Kp ${fmt(sat.geomagnetic_kp, 1)}`);
    setText('orbitalPeriodFoot', fmt(sat.orbital_period_min, 1, ' хв'));
    setText('atmDensity', `${fmt(1.8 + (431 - sat.altitude_km) * 0.06, 1)} ×10⁻¹² kg/m³`);
    setText('solarActivityValue', solarActivityLabel(sat.geomagnetic_kp));
    setText('eclipseStatus', sat.visibility === 'daylight' ? 'НЕМАЄ' : 'У ТІНІ');
    if ($('mapReadout')) $('mapReadout').innerHTML = `LAT ${fmt(sat.latitude_deg, 3, '°')}<br>LON ${fmt(sat.longitude_deg, 3, '°')}`;

    const ring = $('satRing');
    if (ring) ring.style.setProperty('--score', `${clamp(sat.mission_score, 0, 100)}%`);
    setBars('satBattBars', sat.battery_soc_pct);
    setBars('satCommBars', sat.comm_quality_pct);

    // Реалістичні прилад-шкали замість ліній графіка: показують позицію поточного
    // значення на реальному діапазоні (як стрічка швидкості/висоти в кабіні).
    drawScaleGauge('satLatSpark', sat.latitude_deg, -55, 55, {color: 'cyan', minLabel: '55°S', maxLabel: '55°N'});
    drawScaleGauge('satLonSpark', sat.longitude_deg, -180, 180, {color: 'cyan', minLabel: '180°W', maxLabel: '180°E'});
    drawScaleGauge('satAltSpark', sat.altitude_km, 405, 432, {color: 'blue', minLabel: '405 км', maxLabel: '432 км'});
    drawScaleGauge('satVelSpark', sat.velocity_kmh, 27000, 28000, {
        color: 'cyan',
        minLabel: '27000',
        maxLabel: '28000'
    });
    drawScaleGauge('satRadSpark', sat.radiation_index, 0, 80, {color: 'orange', minLabel: '0', maxLabel: '80'});
    drawSparkline('kpSpark', history.map(x => x.geomagnetic_kp), {min: 0, max: 9, color: 'green'});
    drawSparkline('bzSpark', history.map((x, i) => -1.2 + Math.sin(i * .12) * 1.7 + (x.geomagnetic_kp - 2) * .35), {
        min: -8,
        max: 8,
        color: 'blue'
    });
    drawSparkline('densSpark', history.map(x => 1.8 + (431 - x.altitude_km) * .06), {color: 'purple'});
    drawSparkline('periodSpark', history.map(x => 92 + (x.altitude_km - 419) * .025), {color: 'cyan'});
}

function updateDrone(drone, history) {
    setText('uavScenarioName', drone.scenario);
    const geo = dronePseudoGeo(drone);

    setText('uavAlt', fmt(geo.alt, 1, ' м'));
    setText('uavSpeed', fmt(geo.speed, 1, ' км/год'));
    setText('uavRssi', `${fmt(-52 - drone.risk * 38 - Math.sin(drone.t * .1) * 4, 0)} dBm`);
    setText('uavLink', drone.risk > .75 ? 'НЕСТАБІЛЬНИЙ' : 'НАДІЙНИЙ');
    setText('uavSummaryLine', `t=${fmt(drone.t, 1, 's')} | I=${fmt(drone.Icurrent, 2)}A/45A | T=${fmt(drone.Tcurrent, 1)}°C/90°C | P_total=${fmt(drone.electrical_power_W, 1)}W | V=${fmt(drone.voltage_V, 2)}V | RPM=${fmtInt(drone.rpm)} | η=${fmt(drone.efficiency_percent, 1)}% | SOC=${fmt(drone.battery_soc_percent, 1)}%`);

    setText('drCurrentValue', fmt(drone.Icurrent, 1, 'A'));
    setText('drTempValue', fmt(drone.Tcurrent, 1, '°C'));
    setText('drRiskValue', fmt(drone.risk, 3));
    setText('drHeatValue', fmt(drone.electrical_power_W, 1, 'W'));
    setText('drVoltageValue', fmt(drone.voltage_V, 2, 'V'));
    setText('drRpmValue', fmtInt(drone.rpm));
    setText('drMagValue', fmt(drone.magnet_health_percent, 1, '%'));
    setText('drEffValue', fmt(drone.efficiency_percent, 1, '%'));
    setText('drBattValue', fmt(drone.battery_soc_percent, 0, '%'));
    setText('drBattBig', fmt(drone.battery_soc_percent, 1, '%'));
    setText('drThrottleValue', fmt(drone.throttle_percent, 0, '%'));
    setText('drHeatRateValue', fmt(drone.heating_rate_C_per_s, 3, '°C/s'));
    setText('drCoolRateValue', fmt(drone.cooling_rate_C_per_s, 3, '°C/s'));
    setText('drStatusText', drone.status);
    setText('drStatusBadge', drone.status);
    setText('drPhase', drone.mission_phase);
    setText('drMargin', fmt(drone.thermal_margin_C, 1, ' °C'));
    setText('drDemag', drone.demag_risk < .3 ? 'LOW' : drone.demag_risk < .7 ? 'MEDIUM' : 'HIGH');
    setText('drBattSide', fmt(drone.battery_soc_percent, 1, '%'));
    setText('drLinkSide', drone.risk > .75 ? 'НЕСТАБІЛЬНИЙ' : 'НАДІЙНИЙ');
    setText('drMissionTime', formatDuration(drone.t));

    const riskPct = clamp(drone.risk * 100, 0, 100);
    setProgress('riskFill', riskPct);
    setText('riskText', `Risk K = ${fmt(drone.risk, 3)} | ${drone.status}`);
    const orb = $('droneOrb');
    if (orb) orb.className = `safe-orb ${statusClass(drone.status)}`;
    setProgress('drBattProgress', drone.battery_soc_percent);
    setProgress('drThrProgress', drone.throttle_percent);

    const pseudoHistory = history.map((x) => ({...dronePseudoGeo({...drone, t: x.t, risk: x.risk}), ...x}));
    drawSparkline('uavLatSpark', pseudoHistory.map(x => x.lat), {thin: true, color: 'cyan'});
    drawSparkline('uavLonSpark', pseudoHistory.map(x => x.lon), {thin: true, color: 'cyan'});
    drawSparkline('uavAltSpark', pseudoHistory.map(x => x.alt), {min: 0, max: 160, thin: true, color: 'blue'});
    drawSparkline('uavSpeedSpark', pseudoHistory.map(x => x.speed), {min: 0, max: 90, thin: true, color: 'cyan'});
    drawSparkline('uavHeadSpark', pseudoHistory.map(x => x.heading), {min: 0, max: 360, thin: true, color: 'cyan'});
    drawSparkline('uavRangeSpark', pseudoHistory.map(x => x.range), {min: 0, max: 15, thin: true, color: 'cyan'});
    drawSparkline('uavRssiSpark', history.map(x => -52 - x.risk * 38), {
        min: -100,
        max: -40,
        thin: true,
        color: 'blue'
    });

    drawSparkline('drCurrentChart', history.map(x => x.Icurrent), {min: 0, max: 45, color: 'cyan'});
    drawSparkline('drTempChart', history.map(x => x.Tcurrent), {min: 20, max: 100, color: 'orange'});
    drawSparkline('drRiskChart', history.map(x => x.risk), {min: 0, max: 1, color: 'purple'});
    drawSparkline('drHeatChart', history.map(x => x.electrical_power_W), {min: 0, max: 1100, color: 'cyan'});
    drawSparkline('drVoltageChart', history.map(x => x.voltage_V), {min: 18, max: 26, color: 'green'});
    drawSparkline('drRpmChart', history.map(x => x.rpm), {min: 0, max: 20000, color: 'blue'});
    drawSparkline('drMagChart', history.map(x => x.magnet_health_percent), {min: 0, max: 100, color: 'green'});
    drawSparkline('drEffChart', history.map(x => x.efficiency_percent), {min: 40, max: 90, color: 'orange'});
    drawSparkline('drHeatRateChart', history.map(x => x.heating_rate_C_per_s), {min: 0, max: 2, color: 'red'});
    drawSparkline('drCoolRateChart', history.map(x => x.cooling_rate_C_per_s), {min: 0, max: 2, color: 'cyan'});
}

function dronePseudoGeo(drone) {
    const t = Number(drone.t) || 0;
    const r = 0.055 + 0.012 * Math.sin(t * .013);
    const lat = KYIV.lat + Math.sin(t * .018) * r + Math.sin(t * .071) * .006;
    const lon = KYIV.lon + Math.cos(t * .016) * r * 1.55;
    const alt = 30 + (drone.throttle_percent || 50) * 1.25 + Math.sin(t * .07) * 7;
    const speed = 15 + (drone.rpm || 10000) * 0.004 + Math.sin(t * .11) * 3;
    const heading = (90 + t * 2.7 + Math.sin(t * .05) * 35) % 360;
    const dx = (lon - KYIV.lon) * 72;
    const dy = (lat - KYIV.lat) * 111;
    const range = Math.sqrt(dx * dx + dy * dy);
    return {lat, lon, alt, speed, heading, range};
}

function updateLogs(satLog, droneLog) {
    renderLog('satEventLog', satLog, 'SAT');
    renderLog('droneEventLog', droneLog, 'UAV');
}

function renderLog(id, entries, source) {
    const el = $(id);
    if (!el) return;
    const list = [...(entries || [])].reverse().slice(0, 7);
    el.innerHTML = list.map((entry, i) => {
        const level = entry.level || 'info';
        const tag = level === 'alarm' ? 'ALARM' : level === 'warning' ? 'WARNING' : i === list.length - 1 ? 'INIT' : 'INFO';
        return `<div class="event-row ${level}"><em>${nowTime()}</em><span class="event-dot"></span><span><strong>${source}:</strong> ${escapeHtml(entry.message || entry)}</span><b>${tag}</b></div>`;
    }).join('') || `<div class="event-row"><em>${nowTime()}</em><span class="event-dot"></span><span>Очікування телеметрії...</span><b>INIT</b></div>`;
}

function escapeHtml(text) {
    return String(text).replace(/[&<>'"]/g, (ch) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        "'": '&#039;',
        '"': '&quot;'
    }[ch]));
}

function updateAi(sat, drone, satHistory, droneHistory, logs) {
    const cpu = clamp(42 + drone.risk * 48 + sat.radiation_index * .18, 10, 96);
    const throughput = clamp(50 + sat.comm_quality_pct * .17 - drone.risk * 8, 22, 95);
    const ram = clamp(37 + satHistory.length * .05 + droneHistory.length * .04, 20, 78);
    const disk = clamp(12 + logs.length * 4 + Math.sin(drone.t * .04) * 6, 5, 48);
    const gpu = clamp(62 + drone.risk * 22 + Math.sin(drone.t * .025) * 9, 44, 93);
    const conf = clamp((sat.mission_score * .62) + (100 - drone.risk * 100) * .28 + 10, 35, 98);

    setLoad('aiCpu', cpu, 'cyan');
    setLoad('aiThrough', throughput, 'orange');
    setLoad('aiRam', ram, 'green');
    setLoad('aiDisk', disk, 'blue');
    setLoad('aiGpu', gpu, 'purple');
    setLoad('aiConfidence', conf, 'red');
    setText('aiLoadFooter', fmt(cpu, 0, '%'));
    setText('gpuTemp', fmt(45 + gpu * .22, 1, '°C'));
    setText('latencyText', fmtInt(80 + cpu * .8, ' ms'));
    drawSparkline('aiLoadSpark', satHistory.map((x, i) => 40 + (x.mission_score || 80) * .25 + Math.sin(i * .7) * 12), {
        min: 0,
        max: 100,
        color: 'cyan'
    });

    setText('aiMonTime', formatDuration(sat.t_sim_s));
    const alertCount = [...(logs || [])].filter(x => ['warning', 'alarm'].includes(x.level)).length;
    setText('aiAlertCount', String(alertCount));
    const maxMission = Math.max(...satHistory.map(x => x.mission_score || 0), sat.mission_score || 0);
    setText('aiMaxMission', fmt(maxMission, 0, '%'));
    const altVals = satHistory.map(x => x.altitude_km).filter(Number.isFinite);
    const altMin = Math.min(...altVals, sat.altitude_km);
    const altMax = Math.max(...altVals, sat.altitude_km);
    setText('aiAltRange', `${fmt(altMin, 0)}–${fmt(altMax, 0)} км`);
    const avgBatt = avg([...satHistory.map(x => x.battery_soc_pct), ...droneHistory.map(x => x.battery_soc_percent)]);
    setText('aiAvgBatt', fmt(avgBatt, 1, '%'));
    setText('aiEclipseCount', String(satHistory.filter(x => x.system_status !== 'NOMINAL' || (x.battery_soc_pct || 100) < 82).length));
    setText('aiReactionCount', String((logs || []).length + Math.round(drone.risk * 8)));
    const maxRisk = Math.max(...droneHistory.map(x => x.risk || 0), drone.risk || 0);
    setText('aiMaxRisk', fmt(maxRisk, 3));
    setText('aiEff', fmt(conf, 1, '%'));
    setText('aiCommStable', fmt(sat.comm_quality_pct, 1, '%'));
    setText('aiTrajDev', fmt(sat.attitude_error_deg * 82 + drone.risk * 1.2, 3, ' m'));

    drawMissionChart(satHistory, droneHistory);
    updateInsights(sat, drone);
}

function setLoad(prefix, value, color) {
    setText(`${prefix}Text`, fmt(value, 0, '%'));
    const bar = $(`${prefix}Bar`);
    if (bar) {
        bar.style.width = `${clamp(value, 0, 100)}%`;
        const colors = {
            cyan: 'linear-gradient(90deg, #22d3ee, #38bdf8)', orange: 'linear-gradient(90deg, #f7c948, #fb923c)',
            green: 'linear-gradient(90deg, #00ff88, #22d3ee)', blue: 'linear-gradient(90deg, #38bdf8, #22d3ee)',
            purple: 'linear-gradient(90deg, #c084fc, #22d3ee)', red: 'linear-gradient(90deg, #ff3158, #fb923c)',
        };
        bar.style.background = colors[color] || colors.cyan;
    }
}

function avg(values) {
    const clean = values.filter(v => Number.isFinite(Number(v))).map(Number);
    return clean.length ? clean.reduce((a, b) => a + b, 0) / clean.length : 0;
}

function updateInsights(sat, drone) {
    const insights = [];
    if (sat.system_status === 'NOMINAL' && drone.status === 'SAFE') insights.push(['green', '↟', 'Стабільна місія', 'Усі ключові системи працюють у межах номінальних параметрів. Ризики низькі.']);
    else insights.push(['yellow', '⚠', 'Посилений моніторинг', 'Один або кілька каналів вийшли з ідеального коридору. Алгоритми підвищили частоту перевірки.']);
    insights.push(['cyan', 'ⓘ', 'Оптимізація маршруту', `Рекомендовано м'яке коригування траєкторії для економії енергії. Зв'язок ${fmt(sat.comm_quality_pct, 1, '%')}.`]);
    if (drone.Tcurrent > 58 || drone.risk > .4) insights.push(['orange', '△', 'Підвищене теплове навантаження', `Температура UAV ${fmt(drone.Tcurrent, 1, '°C')}. Модель нагріву рекомендує контролювати throttle.`]);
    insights.push(['purple', '⌁', 'Модель Battery Decay', `Прогноз ресурсу батареї: ${fmt((drone.battery_soc_percent / Math.max(.1, drone.Icurrent)) * 1.2, 1, ' год')} до критичного запасу.`]);
    insights.push(['green', '✓', 'Якість зв\'язку', 'Канал стабільний. Втрат пакетів у синтетичній моделі не виявлено.']);

    const el = $('insightList');
    if (!el) return;
    el.innerHTML = insights.map(([color, icon, title, text]) => `<div><i class="${color}">${icon}</i><span><b>${title}</b><small>${text}</small></span></div>`).join('');
}

function drawMissionChart(satHistory, droneHistory) {
    const canvas = $('aiMissionChart');
    const prepared = prepareCanvas(canvas);
    if (!prepared) return;
    const {ctx, width, height} = prepared;
    ctx.clearRect(0, 0, width, height);
    const pad = {l: 42, r: 14, t: 12, b: 26};
    const w = width - pad.l - pad.r;
    const h = height - pad.t - pad.b;

    ctx.strokeStyle = 'rgba(80,220,255,.12)';
    ctx.lineWidth = 1;
    ctx.font = "11px 'Share Tech Mono'";
    ctx.fillStyle = 'rgba(198,216,239,.55)';
    for (let y = 0; y <= 4; y++) {
        const yy = pad.t + h * y / 4;
        ctx.beginPath();
        ctx.moveTo(pad.l, yy);
        ctx.lineTo(pad.l + w, yy);
        ctx.stroke();
        ctx.fillText(String(100 - y * 25), 6, yy + 4);
    }

    const satVals = satHistory.slice(-80).map(x => x.mission_score || 0);
    const riskVals = droneHistory.slice(-80).map(x => (x.risk || 0) * 100);
    drawLine(ctx, satVals, pad, w, h, ['rgba(34,211,238,.95)', 'rgba(34,211,238,.12)']);
    drawLine(ctx, riskVals, pad, w, h, ['rgba(192,132,252,.95)', 'rgba(192,132,252,.13)']);

    ctx.fillStyle = '#22d3ee';
    ctx.fillText('MISSION INDEX', pad.l + w - 130, pad.t + 16);
    ctx.fillStyle = '#c084fc';
    ctx.fillText('RISK K', pad.l + w - 230, pad.t + 16);
}

function drawLine(ctx, values, pad, w, h, colors) {
    if (values.length < 2) return;
    const pts = values.map((v, i) => ({
        x: pad.l + (i / (values.length - 1)) * w,
        y: pad.t + h - clamp(v, 0, 100) / 100 * h
    }));
    ctx.beginPath();
    pts.forEach((p, i) => i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y));
    ctx.strokeStyle = colors[0];
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.lineTo(pad.l + w, pad.t + h);
    ctx.lineTo(pad.l, pad.t + h);
    ctx.closePath();
    const fill = ctx.createLinearGradient(0, pad.t, 0, pad.t + h);
    fill.addColorStop(0, colors[1]);
    fill.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = fill;
    ctx.fill();
}

function redrawAll() {
    if (state.sat) drawOrbitMap(state.sat, state.satHistory);
    if (state.sat && state.drone) updateAi(state.sat, state.drone, state.satHistory, state.droneHistory, state.eventLog || []);
}

async function updateTelemetry() {
    try {
        const data = await apiGet('/api/telemetry');
        state.failureCount = 0;
        state.paused = data.paused;
        state.sat = data.satellite;
        state.drone = data.drone;
        state.satHistory = data.satellite_history || [];
        state.droneHistory = data.drone_history || [];
        state.eventLog = data.event_log || [];
        state.droneLog = data.drone_log || [];

        document.querySelectorAll('#pauseBtn').forEach((btn) => btn.textContent = data.paused ? 'RESUME' : 'PAUSE');
        if ($('pausedFlag')) $('pausedFlag').style.display = data.paused ? 'block' : 'none';
        markActiveScenarios(data.satellite, data.drone);
        updateSatellite(data.satellite, state.satHistory);
        updateDrone(data.drone, state.droneHistory);
        updateLogs(data.event_log || [], data.drone_log || []);
        updateAi(data.satellite, data.drone, state.satHistory, state.droneHistory, data.event_log || []);
        drawOrbitMap(data.satellite, state.satHistory);
    } catch (err) {
        state.failureCount += 1;
        if (state.failureCount > 2) {
            renderLog('satEventLog', [{
                level: 'alarm',
                message: `Backend не відповідає. Запусти: uvicorn backend:app --reload. ${err.message}`
            }], 'SYS');
        }
    }
}

function project(lon, lat, width, height) {
    return {x: ((lon + 180) / 360) * width, y: ((90 - lat) / 180) * height};
}

function angularDistance(lat1, lon1, lat2, lon2) {
    const p1 = rad(lat1), p2 = rad(lat2), dl = rad(lon2 - lon1);
    const s = Math.sin(p1) * Math.sin(p2) + Math.cos(p1) * Math.cos(p2) * Math.cos(dl);
    return Math.acos(clamp(s, -1, 1)) * 180 / Math.PI;
}


const cityLights = [
    [-74, 40], [-118, 34], [-95, 29], [-87, 41], [-99, 19], [-46, -23], [-58, -34], [-3, 52], [2, 48], [13, 52], [30, 50], [37, 55], [29, 41], [-4, 40], [12, 42], [31, 30], [44, 33], [55, 25], [72, 19], [77, 28], [90, 23], [100, 13], [106, 10], [116, 39], [121, 31], [139, 35], [126, 37], [151, -34]
];

function drawOrbitMap(sat, history) {
    const canvas = $('orbitCanvas');
    const prepared = prepareCanvas(canvas);
    if (!prepared || !sat) return;
    const {ctx, width, height} = prepared;
    ctx.clearRect(0, 0, width, height);

    const bg = ctx.createLinearGradient(0, 0, 0, height);
    bg.addColorStop(0, '#06142a');
    bg.addColorStop(.5, '#07162b');
    bg.addColorStop(1, '#020713');
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, width, height);

    // star field behind the map
    ctx.fillStyle = 'rgba(255,255,255,.42)';
    for (let i = 0; i < 110; i++) {
        const x = (Math.sin(i * 91.7) * .5 + .5) * width;
        const y = (Math.cos(i * 43.2) * .5 + .5) * height;
        ctx.fillRect(x, y, i % 7 === 0 ? 1.6 : .9, i % 7 === 0 ? 1.6 : .9);
    }

    // ocean glow
    const ocean = ctx.createRadialGradient(width * .48, height * .52, 10, width * .48, height * .52, width * .75);
    ocean.addColorStop(0, 'rgba(17, 82, 128, .22)');
    ocean.addColorStop(1, 'rgba(2, 7, 15, .1)');
    ctx.fillStyle = ocean;
    ctx.fillRect(0, 0, width, height);

    // graticule
    ctx.strokeStyle = 'rgba(84,180,230,.12)';
    ctx.lineWidth = 1;
    for (let lon = -180; lon <= 180; lon += 30) {
        const a = project(lon, -85, width, height), b = project(lon, 85, width, height);
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
    }
    for (let lat = -60; lat <= 60; lat += 30) {
        const a = project(-180, lat, width, height), b = project(180, lat, width, height);
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
    }

    // Earth photo, if it loaded successfully; otherwise fall back to the vector map
    if (earthImgLoaded) {
        ctx.globalAlpha = 0.92;
        ctx.drawImage(earthImg, 0, 0, width, height);
        ctx.globalAlpha = 1;
    } else {
        continents.forEach((poly, idx) => {
            ctx.beginPath();
            poly.forEach(([lon, lat], i) => {
                const p = project(lon, lat, width, height);
                i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y);
            });
            ctx.closePath();
            const land = ctx.createLinearGradient(0, 0, width, height);
            land.addColorStop(0, idx === 8 ? 'rgba(170,190,205,.35)' : 'rgba(28, 91, 78, .68)');
            land.addColorStop(1, idx === 8 ? 'rgba(130,160,180,.22)' : 'rgba(86, 82, 47, .68)');
            ctx.fillStyle = land;
            ctx.fill();
            ctx.strokeStyle = 'rgba(120, 210, 190, .22)';
            ctx.lineWidth = 1;
            ctx.stroke();
        });
    }

    // Day/night shading using real solar point from the Python model
    const step = Math.max(6, Math.floor(width / 160));
    for (let x = 0; x < width; x += step) {
        for (let y = 0; y < height; y += step) {
            const lon = x / width * 360 - 180;
            const lat = 90 - y / height * 180;
            const d = angularDistance(lat, lon, sat.solar_lat_deg, sat.solar_lon_deg);
            const alpha = clamp((d - 86) / 42, 0, 1) * .58;
            if (alpha > .01) {
                ctx.fillStyle = `rgba(0, 0, 0, ${alpha})`;
                ctx.fillRect(x, y, step + 1, step + 1);
            }
        }
    }

    // night city lights
    cityLights.forEach(([lon, lat], i) => {
        const d = angularDistance(lat, lon, sat.solar_lat_deg, sat.solar_lon_deg);
        if (d < 94) return;
        const p = project(lon, lat, width, height);
        const a = clamp((d - 90) / 35, 0, 1);
        ctx.fillStyle = `rgba(250, 210, 92, ${0.22 + a * .55})`;
        ctx.beginPath();
        ctx.arc(p.x, p.y, 1.1 + (i % 3) * .45, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowColor = 'rgba(250,210,92,.45)';
        ctx.shadowBlur = 6;
        ctx.fill();
        ctx.shadowBlur = 0;
    });

    // terminator helper
    drawTerminator(ctx, width, height, sat);

    // Kyiv ground station marker


    // history ground track
    drawTrack(ctx, width, height, history, 'rgba(34,211,238,.90)', false);
    drawPredictedTrack(ctx, width, height, sat, history);

    // solar point
    const sun = project(sat.solar_lon_deg, sat.solar_lat_deg, width, height);
    ctx.fillStyle = 'rgba(247,201,72,.16)';
    ctx.beginPath();
    ctx.arc(sun.x, sun.y, 34, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#f7c948';
    ctx.beginPath();
    ctx.arc(sun.x, sun.y, 4, 0, Math.PI * 2);
    ctx.fill();

    // satellite footprint and marker
    const p = project(sat.longitude_deg, sat.latitude_deg, width, height);
    const fp = clamp((sat.footprint_km / 40075) * width, 28, width * .23);
    ctx.strokeStyle = 'rgba(34,211,238,.25)';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([3, 5]);
    ctx.beginPath();
    ctx.arc(p.x, p.y, fp, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(34,211,238,.15)';
    ctx.beginPath();
    ctx.arc(p.x, p.y, 20, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#f7c948';
    ctx.beginPath();
    ctx.arc(p.x, p.y, 6, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#22d3ee';
    ctx.lineWidth = 1;
    ctx.strokeRect(p.x - 10, p.y - 10, 20, 20);
    ctx.font = "12px 'Share Tech Mono'";
    ctx.fillStyle = '#e2eeff';
    ctx.fillText('ISS', p.x + 13, p.y - 13);
}

function drawTrack(ctx, width, height, history, color, dashed) {
    if (!history || history.length < 2) return;
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    if (dashed) ctx.setLineDash([7, 7]);
    ctx.beginPath();
    let prev = null;
    history.forEach((point, i) => {
        const p = project(point.longitude_deg, point.latitude_deg, width, height);
        if (!prev || Math.abs(p.x - prev.x) > width / 2) ctx.moveTo(p.x, p.y); else ctx.lineTo(p.x, p.y);
        prev = p;
    });
    ctx.stroke();
    ctx.restore();
}

function drawPredictedTrack(ctx, width, height, sat, history) {
    const last = history && history.length > 2 ? history[history.length - 1] : sat;
    const prev = history && history.length > 2 ? history[history.length - 3] : null;
    let dlon = prev ? last.longitude_deg - prev.longitude_deg : 8;
    let dlat = prev ? last.latitude_deg - prev.latitude_deg : 2;
    if (Math.abs(dlon) > 120) dlon = dlon > 0 ? dlon - 360 : dlon + 360;
    dlon *= .55;
    dlat *= .55;
    const predicted = [];
    let lon = sat.longitude_deg, lat = sat.latitude_deg;
    for (let i = 0; i < 120; i++) {
        lon += dlon * .18;
        lat += dlat * .18;
        if (lat > 51.6 || lat < -51.6) {
            dlat *= -1;
            lat = clamp(lat, -51.6, 51.6);
        }
        lon = ((lon + 180) % 360 + 360) % 360 - 180;
        predicted.push({longitude_deg: lon, latitude_deg: lat});
    }
    drawTrack(ctx, width, height, predicted, 'rgba(247,201,72,.82)', true);
}

function drawTerminator(ctx, width, height, sat) {
    ctx.save();
    ctx.strokeStyle = 'rgba(247,201,72,.28)';
    ctx.lineWidth = 1;
    ctx.setLineDash([5, 6]);
    ctx.beginPath();
    for (let lon = -180; lon <= 180; lon += 3) {
        const dl = rad(lon - sat.solar_lon_deg);
        const tanLat = -Math.cos(dl) / Math.tan(rad(sat.solar_lat_deg || .1));
        const lat = clamp(Math.atan(tanLat) * 180 / Math.PI, -85, 85);
        const p = project(lon, lat, width, height);
        lon === -180 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y);
    }
    ctx.stroke();
    ctx.restore();
}

async function boot() {
    attachUi();
    const meta = await apiGet('/api/meta');
    state.meta = meta;
    populateScenarios(meta);
    await updateTelemetry();
    setInterval(updateTelemetry, 450);
}

boot();
