from __future__ import annotations

import threading
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from simulation import (
    DRONE_SCENARIOS,
    SATELLITE_SCENARIOS,
    DroneSimulator,
    SatelliteSimulator,
    simulation_meta,
)

# ============================================================
# SKY & SPACE SENTINEL - SIMPLE FETCH BACKEND
# ------------------------------------------------------------
# No WebSocket here. The browser calls /api/telemetry with fetch()
# every few hundred milliseconds. Python remains the simulation core;
# HTML/CSS/JS is only the visual dashboard.
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Sky & Space Sentinel API", version="2.0")

satellite = SatelliteSimulator()
drone = DroneSimulator()

paused = False
lock = threading.Lock()

sat_history: deque[dict] = deque(maxlen=420)
drone_history: deque[dict] = deque(maxlen=420)
event_log: deque[dict] = deque(maxlen=18)
drone_log: deque[dict] = deque(maxlen=14)


def _round_dict(data: dict, digits: int = 4) -> dict:
    """Keep JSON stable and compact without losing useful telemetry precision."""
    out: dict[str, Any] = {}
    for key, value in data.items():
        out[key] = round(value, digits) if isinstance(value, float) else value
    return out


def _compact_sat(sample: dict) -> dict:
    keys = [
        "utc_time",
        "t_sim_s",
        "latitude_deg",
        "longitude_deg",
        "altitude_km",
        "velocity_kmh",
        "battery_soc_pct",
        "solar_power_kw",
        "radiation_index",
        "comm_quality_pct",
        "mission_score",
        "system_status",
        "geomagnetic_kp",
        "surface_temp_c",
        "wind_speed_kmh",
        "cloud_cover_pct",
    ]
    return {key: sample[key] for key in keys if key in sample}


def _compact_drone(sample: dict) -> dict:
    keys = [
        "t",
        "Tcurrent",
        "Icurrent",
        "risk",
        "battery_soc_percent",
        "rpm",
        "thermal_margin_C",
        "efficiency_percent",
        "status",
        "heat_power_W",
        "voltage_V",
        "throttle_percent",
        "magnet_health_percent",
        "heating_rate_C_per_s",
        "cooling_rate_C_per_s",
        "demag_risk",
    ]
    return {key: sample[key] for key in keys if key in sample}


def _event_level(status: str) -> str:
    status = (status or "").upper()
    if status in {"CRITICAL", "DANGER"}:
        return "alarm"
    if status in {"ALERT", "CAUTION", "WATCH"}:
        return "warning"
    return "info"


def _ua_sat_event(sample: dict) -> str:
    scenario = sample.get("scenario", "normal")
    status = sample.get("system_status", "NOMINAL")
    if scenario == "geomagnetic":
        return "Магнітна буря - Kp підвищений, радіаційний та комунікаційний запас зменшено"
    if scenario == "solar_flare":
        return "Сонячний спалах - radiation index зростає, канал зв'язку перевіряється"
    if scenario == "drag":
        return "Атмосферний drag - висота орбіти повільно знижується, потрібне планування reboost"
    if scenario == "blackout":
        return "Комунікаційний blackout - телеметрія нестабільна, бортові системи працюють автономно"
    if scenario == "debris":
        return "Маневр ухилення - короткий імпульс Delta-V та корекція орієнтації активні"
    if scenario == "eclipse":
        return "Орбітальна тінь - сонячна генерація низька, батарея переходить у режим економії"
    if scenario == "thermal":
        return "Термоконтроль - температура та CO₂ відходять від ідеального коридору"
    if status == "NOMINAL":
        return "Номінальний режим - орбіта, енергетика, зв'язок і середовище в межах норми"
    return "Mission watch - один або кілька каналів телеметрії потребують контролю"


def _ua_drone_event(sample: dict) -> str:
    status = sample.get("status", "SAFE")
    phase = sample.get("mission_phase", "CRUISE")
    temp = sample.get("Tcurrent", 0.0)
    risk = sample.get("risk", 0.0)
    if status == "DANGER":
        return f"Критичний тепловий режим - risk K={risk:.2f}, рекомендовано негайно зменшити навантаження"
    if status == "CAUTION":
        return f"Попередження - температура двигуна {temp:.1f}°C, система контролює тепловий запас"
    if "CLIMB" in phase or "PAYLOAD" in phase:
        return f"Підвищене навантаження у фазі {phase}, теплову модель активовано"
    return "UAV стабільний - струм, температура, батарея і лінк у допустимих межах"


def _append_unique_log(storage: deque[dict], message: str, status: str) -> None:
    if storage and storage[-1]["message"] == message:
        return
    storage.append({"message": message, "level": _event_level(status)})


def _tick() -> tuple[dict, dict]:
    """Advance both simulators by one browser tick."""
    sat_sample = satellite.step().to_dict()

    # Drone has small dt, so several internal frames match one browser refresh.
    drone_sample = drone.step().to_dict()
    for _ in range(5):
        drone_sample = drone.step().to_dict()

    sat_sample = _round_dict(sat_sample)
    drone_sample = _round_dict(drone_sample)

    sat_history.append(_compact_sat(sat_sample))
    drone_history.append(_compact_drone(drone_sample))

    _append_unique_log(event_log, _ua_sat_event(sat_sample), sat_sample.get("system_status", "NOMINAL"))
    _append_unique_log(drone_log, _ua_drone_event(drone_sample), drone_sample.get("status", "SAFE"))

    return sat_sample, drone_sample


# Warm start so first page load has history and sparklines.
with lock:
    for _ in range(24):
        _tick()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(BASE_DIR / "index.html")


@app.get("/script.js")
def script() -> FileResponse:
    return FileResponse(BASE_DIR / "script.js", media_type="application/javascript")


@app.get("/styles.css")
def styles() -> FileResponse:
    return FileResponse(BASE_DIR / "styles.css", media_type="text/css")


@app.get("/index.js")
def index_js() -> FileResponse:
    return FileResponse(BASE_DIR / "index.js", media_type="application/javascript")


@app.get("/earth.jpg")
def earth_photo() -> FileResponse:
    return FileResponse(BASE_DIR / "earth.jpg")


@app.get("/api/meta")
def meta() -> dict:
    return simulation_meta()


@app.get("/api/telemetry")
def telemetry() -> JSONResponse:
    global paused
    with lock:
        if paused:
            sat_sample = satellite.last_sample.to_dict() if satellite.last_sample else satellite.step().to_dict()
            drone_sample = drone.last_sample.to_dict() if drone.last_sample else drone.step().to_dict()
            sat_sample = _round_dict(sat_sample)
            drone_sample = _round_dict(drone_sample)
        else:
            sat_sample, drone_sample = _tick()

        payload = {
            "paused": paused,
            "satellite": sat_sample,
            "drone": drone_sample,
            "satellite_history": list(sat_history),
            "drone_history": list(drone_history),
            "event_log": list(event_log),
            "drone_log": list(drone_log),
            "server_mode": "fetch",
        }
    return JSONResponse(payload)


class ScenarioChange(BaseModel):
    key: str | None = None
    name: str | None = None


@app.post("/api/satellite/scenario")
def set_satellite_scenario(body: ScenarioChange) -> dict:
    key = body.key or "normal"
    allowed = {s.key for s in SATELLITE_SCENARIOS}
    if key not in allowed:
        key = "normal"

    with lock:
        satellite.set_scenario(key)
        sat_history.clear()
        event_log.clear()
        for _ in range(16):
            _tick()

    return {"ok": True, "scenario": key}


@app.post("/api/drone/scenario")
def set_drone_scenario(body: ScenarioChange) -> dict:
    name = body.name or "Normal mission"
    if name not in DRONE_SCENARIOS:
        name = "Normal mission"

    with lock:
        drone.set_scenario(name)
        drone_history.clear()
        drone_log.clear()
        for _ in range(16):
            _tick()

    return {"ok": True, "scenario": name}


@app.post("/api/control/{action}")
def control(action: str) -> dict:
    global paused
    action = action.lower().strip()

    with lock:
        if action == "pause":
            paused = True
        elif action == "resume":
            paused = False
        elif action == "toggle":
            paused = not paused
        elif action == "reset":
            satellite.reset()
            drone.reset()
            sat_history.clear()
            drone_history.clear()
            event_log.clear()
            drone_log.clear()
            paused = False
            for _ in range(24):
                _tick()

    return {"ok": True, "paused": paused}
