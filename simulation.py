from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple


# ============================================================
#  SKY & SPACE SENTINEL - PURE PYTHON SIMULATION CORE
#  Без PyQt, без графічного desktop-вікна.
#
#  Тут живе тільки фізика / телеметрія:
#  - ISS-like satellite mission simulation
#  - UAV / drone thermal-electric simulation
#
#  backend.py віддає ці дані як JSON, а index.html + script.js
#  постійно забирають їх через fetch().
# ============================================================


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def wrap_lon(lon_deg: float) -> float:
    """Wrap longitude to [-180, 180]."""
    return ((lon_deg + 180.0) % 360.0) - 180.0


def phase_smooth(current: float, target: float, alpha: float, noise: float = 0.0, rng=random) -> float:
    """Smooth first-order response with optional sensor/model noise.

    `rng` defaults to the global `random` module (identical to the old behaviour).
    Pass a `random.Random(seed)` instance for a reproducible simulation.
    """
    return current + alpha * (target - current) + rng.gauss(0.0, noise)


def gauss_score(value: float, center: float, sigma: float) -> float:
    """Gaussian health score around the expected scientific operating point."""
    return math.exp(-0.5 * ((value - center) / max(sigma, 1e-9)) ** 2)


def angular_distance_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    s = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dlon)
    return math.degrees(math.acos(clamp(s, -1.0, 1.0)))


# ============================================================
#  SATELLITE / ISS-LIKE SIMULATION
# ============================================================


@dataclass
class SatelliteConfig:
    sat_name: str = "ISS"
    sat_cat_nr: int = 25544

    earth_radius_km: float = 6371.0
    mu_earth_km3_s2: float = 398600.4418
    j2: float = 1.08263e-3  # коефіцієнт сплюснутості Землі (для вузлової прецесії)

    inclination_deg: float = 51.64
    mean_altitude_km: float = 419.5
    mean_velocity_kmh: float = 27570.0  # довідкове значення; реальна швидкість рахується динамічно з vis-viva
    orbital_period_min: float = 92.68  # довідкове значення; реальний період рахується динамічно

    sim_step_s: float = 6.0

    # --- Атмосферне гальмування (експоненційна атмосфера + формула Кінга-Хеле) ---
    ballistic_coefficient_m2_per_kg: float = 0.010  # Cd*A/m, ISS-масштаб
    atm_ref_altitude_km: float = 400.0
    atm_ref_density_kg_m3: float = 3.0e-12  # густина атмосфери на atm_ref_altitude_km
    atm_scale_height_km: float = 58.0

    # --- Ємність енергосистеми станції (для перерахунку power_balance -> SoC) ---
    station_battery_capacity_kWh: float = 95.0

    # --- Наукові ліміти для скорингу (NASA short-term spaceflight limits) ---
    co2_limit_mmhg: float = 5.3
    cabin_pressure_tolerance_psi: float = 0.2


@dataclass
class SatelliteScenario:
    key: str
    title: str
    description: str

    altitude_bias_km: float = 0.0
    altitude_wave_km: float = 0.0
    drag_strength: float = 0.0

    solar_power_multiplier: float = 1.0
    eclipse_power_multiplier: float = 1.0

    radiation_multiplier: float = 1.0
    radiation_spike: float = 0.0

    comm_quality_bias: float = 0.0
    comm_drop_chance: float = 0.0

    thermal_bias_c: float = 0.0
    humidity_bias: float = 0.0
    co2_bias: float = 0.0
    pressure_bias: float = 0.0

    control_jitter: float = 0.0
    maneuver_delta_v_ms: float = 0.0


@dataclass
class SatelliteTelemetry:
    utc_time: str
    t_sim_s: float
    scenario: str

    latitude_deg: float
    longitude_deg: float
    altitude_km: float
    velocity_kmh: float
    velocity_ms: float
    orbital_period_min: float
    footprint_km: float
    visibility: str

    solar_lat_deg: float
    solar_lon_deg: float

    cabin_temp_c: float
    cabin_humidity_pct: float
    cabin_pressure_psi: float
    co2_mmhg: float
    o2_mmhg: float

    solar_power_kw: float
    battery_soc_pct: float
    power_balance_kw: float

    radiation_index: float
    geomagnetic_kp: float
    comm_quality_pct: float

    attitude_error_deg: float
    delta_v_ms: float

    surface_temp_c: float
    wind_speed_kmh: float
    cloud_cover_pct: float

    life_support_score: float
    orbit_score: float
    power_score: float
    comm_score: float
    radiation_score: float
    mission_score: float
    system_status: str
    event_message: str

    def to_dict(self) -> dict:
        return asdict(self)


SATELLITE_SCENARIOS: List[SatelliteScenario] = [
    SatelliteScenario(
        key="normal",
        title="Nominal ISS-like orbit",
        description="Базовий стабільний режим: орбіта, енергетика й бортове середовище в нормі.",
    ),
    SatelliteScenario(
        key="geomagnetic",
        title="Geomagnetic storm",
        description="Магнітна буря: росте Kp, збільшується радіаційний ризик і шум зв'язку.",
        radiation_multiplier=1.75,
        radiation_spike=18.0,
    ),
    SatelliteScenario(
        key="solar_flare",
        title="Solar flare radiation event",
        description="Сонячний спалах: різкий ріст radiation index, просідання communication quality.",
        solar_power_multiplier=1.08,
        radiation_multiplier=2.55,
        radiation_spike=38.0,
        comm_quality_bias=-18.0,
        comm_drop_chance=0.035,
    ),
    SatelliteScenario(
        key="drag",
        title="Atmospheric drag increase",
        description="Підвищене гальмування у верхній атмосфері: висота поступово просідає.",
        altitude_bias_km=-4.0,
        altitude_wave_km=1.2,
        drag_strength=1.0,
    ),
    SatelliteScenario(
        key="blackout",
        title="Communication blackout",
        description="Проблема зі зв'язком: telemetry link нестабільний, але бортові системи живі.",
        comm_quality_bias=-55.0,
        comm_drop_chance=0.16,
        radiation_multiplier=1.12,
    ),
    SatelliteScenario(
        key="debris",
        title="Debris avoidance maneuver",
        description="Маневр ухилення від уламків: короткий імпульс, attitude error і delta-v.",
        altitude_wave_km=2.4,
        control_jitter=0.22,
        maneuver_delta_v_ms=1.2,
        solar_power_multiplier=0.97,
    ),
    SatelliteScenario(
        key="eclipse",
        title="Eclipse power saving",
        description="Довша тіньова ділянка: сонячна генерація падає, батарея розряджається швидше.",
        solar_power_multiplier=0.82,
        eclipse_power_multiplier=0.42,
        thermal_bias_c=-0.35,
    ),
    SatelliteScenario(
        key="thermal",
        title="Thermal control anomaly",
        description="Проблема термоконтролю: температура й CO₂ повільно виходять з ідеального діапазону.",
        thermal_bias_c=2.1,
        humidity_bias=6.0,
        co2_bias=0.85,
        solar_power_multiplier=0.94,
    ),
]


def satellite_scenario_by_key(key: str) -> SatelliteScenario:
    for scenario in SATELLITE_SCENARIOS:
        if scenario.key == key:
            return scenario
    return SATELLITE_SCENARIOS[0]


class SatelliteSimulator:
    def __init__(self, cfg: SatelliteConfig | None = None, seed: int | None = None):
        self.cfg = cfg or SatelliteConfig()
        # Якщо seed не задано, поведінка ідентична попередній версії (глобальний random).
        # Якщо seed задано - симуляція стає повністю відтворюваною.
        self.rng = random.Random(seed) if seed is not None else random
        self.scenario = SATELLITE_SCENARIOS[0]
        self.reset()

    def set_scenario(self, key: str) -> None:
        self.scenario = satellite_scenario_by_key(key)
        self.reset()

    def reset(self) -> None:
        self.t_s = 0.0
        self.start_time_utc = datetime.now(timezone.utc)

        self.phase0 = self.rng.uniform(0.0, 2.0 * math.pi)
        self.raan0_deg = self.rng.uniform(-180.0, 180.0)

        self.cabin_temp_c = 23.3 + self.rng.uniform(-0.3, 0.3)
        self.cabin_humidity_pct = 46.0 + self.rng.uniform(-2.0, 2.0)
        self.cabin_pressure_psi = 14.70 + self.rng.uniform(-0.025, 0.025)
        self.co2_mmhg = 3.15 + self.rng.uniform(-0.25, 0.25)
        self.o2_mmhg = 159.0 + self.rng.uniform(-0.6, 0.6)

        self.solar_power_kw = 88.0 + self.rng.uniform(-4.0, 4.0)
        self.battery_soc_pct = 92.0 + self.rng.uniform(-2.5, 2.5)
        self.power_balance_kw = 0.0

        self.radiation_index = 11.0 + self.rng.uniform(-2.0, 2.0)
        self.geomagnetic_kp = 2.2 + self.rng.uniform(-0.6, 0.6)
        self.comm_quality_pct = 96.0 + self.rng.uniform(-2.0, 1.0)

        self.attitude_error_deg = 0.04 + self.rng.uniform(0.0, 0.03)
        self.delta_v_total_ms = 0.0

        self.surface_temp_c = 15.0 + self.rng.uniform(-4.0, 4.0)
        self.wind_speed_kmh = 18.0 + self.rng.uniform(-5.0, 5.0)
        self.cloud_cover_pct = 46.0 + self.rng.uniform(-14.0, 14.0)

        self.drag_altitude_loss_km = 0.0
        # Попередня висота потрібна для оцінки густини атмосфери ρ(h) на цьому кроці
        # (density-модель для формули Кінга-Хеле, див. step()).
        self.prev_altitude_km = self.cfg.mean_altitude_km
        self.last_sample: SatelliteTelemetry | None = None

    def step(self) -> SatelliteTelemetry:
        cfg = self.cfg
        sc = self.scenario
        dt = cfg.sim_step_s
        self.t_s += dt
        t = self.t_s
        now_sim = self.start_time_utc + timedelta(seconds=t)

        # Orbit model: simplified circular inclined orbit + Earth rotation.
        inc = math.radians(cfg.inclination_deg)
        period_s = cfg.orbital_period_min * 60.0
        n = 2.0 * math.pi / period_s
        theta = self.phase0 + n * t

        lat_rad = math.asin(math.sin(inc) * math.sin(theta))
        latitude_deg = math.degrees(lat_rad)

        # J2-прецесія висхідного вузла (реальна орбіта МКС дрейфує ~ -5 deg/добу
        # через сплюснутість Землі; раніше raan0_deg був статичним - це не фізично).
        prev_radius_km = cfg.earth_radius_km + self.prev_altitude_km
        raan_rate_deg_s = (
                -1.5 * math.degrees(n) * cfg.j2 * (cfg.earth_radius_km / prev_radius_km) ** 2 * math.cos(inc)
        )
        current_raan_deg = self.raan0_deg + raan_rate_deg_s * t

        inertial_lon_deg = math.degrees(math.atan2(math.cos(inc) * math.sin(theta), math.cos(theta)))
        earth_rotation_deg = 360.0 * (t / 86164.0)
        longitude_deg = wrap_lon(current_raan_deg + inertial_lon_deg - earth_rotation_deg)

        # Атмосферне гальмування: експоненційна атмосфера ρ(h) = ρ0 * exp(-(h-h0)/H)
        # + втрата висоти за оберт за формулою Кінга-Хеле: Δa/orbit = -2π * B * ρ(h) * a^2.
        # На відміну від попередньої версії, втрата ТІЛЬКИ монотонно накопичується -
        # без маневру reboost орбіта сама по собі ніколи "не загоюється".
        if sc.drag_strength > 0:
            rho_kg_m3 = cfg.atm_ref_density_kg_m3 * math.exp(
                -(self.prev_altitude_km - cfg.atm_ref_altitude_km) / cfg.atm_scale_height_km
            )
            semi_major_m = prev_radius_km * 1000.0
            delta_a_per_orbit_m = (
                    -2.0 * math.pi * cfg.ballistic_coefficient_m2_per_kg * rho_kg_m3 * semi_major_m ** 2
            )
            decay_km_per_s = -delta_a_per_orbit_m / period_s / 1000.0  # додатне значення = втрата висоти
            self.drag_altitude_loss_km += decay_km_per_s * dt * sc.drag_strength

        altitude_km = (
                cfg.mean_altitude_km
                + sc.altitude_bias_km
                - self.drag_altitude_loss_km
                + 4.8 * math.sin(0.31 * theta + 0.70)
                + 2.0 * math.sin(1.75 * theta + 2.10)
                + sc.altitude_wave_km * math.sin(0.018 * t + 0.8)
        )
        altitude_km = clamp(altitude_km, 405.0, 431.0)
        self.prev_altitude_km = altitude_km

        radius_km = cfg.earth_radius_km + altitude_km
        velocity_kmh = math.sqrt(cfg.mu_earth_km3_s2 / radius_km) * 3600.0
        velocity_kmh += 12.0 * math.sin(0.65 * theta + 1.4)
        velocity_kmh += sc.control_jitter * self.rng.gauss(0.0, 25.0)
        velocity_ms = velocity_kmh * 1000.0 / 3600.0

        orbital_period_min = 60.0 * 2.0 * math.pi * radius_km / velocity_kmh
        horizon_half_angle = math.acos(cfg.earth_radius_km / radius_km)
        footprint_km = 2.0 * cfg.earth_radius_km * horizon_half_angle

        # Sun position: схилення Сонця (наближення) + підсонячна довгота (ECEF).
        doy = now_sim.timetuple().tm_yday
        utc_hours = now_sim.hour + now_sim.minute / 60.0 + now_sim.second / 3600.0
        solar_lat_deg = 23.44 * math.sin(2.0 * math.pi * (doy - 80.0) / 365.2422)
        solar_lon_deg = wrap_lon(180.0 - utc_hours * 15.0)

        # sun_sep_deg лишається для косметичної моделі погоди під супутником нижче.
        sun_sep_deg = angular_distance_deg(latitude_deg, longitude_deg, solar_lat_deg, solar_lon_deg)

        # Затемнення: справжня векторна геометрія (циліндрична модель тіні Землі)
        # у інерціальній системі координат, замість кутового порогу "на око".
        j2000_epoch = datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        days_since_j2000 = (now_sim - j2000_epoch).total_seconds() / 86400.0
        gmst_deg = (280.46061837 + 360.98564736629 * days_since_j2000) % 360.0
        sun_ra_deg = (gmst_deg + solar_lon_deg) % 360.0

        raan_rad = math.radians(current_raan_deg)
        sat_x = radius_km * (
                math.cos(raan_rad) * math.cos(theta) - math.sin(raan_rad) * math.sin(theta) * math.cos(inc))
        sat_y = radius_km * (
                math.sin(raan_rad) * math.cos(theta) + math.cos(raan_rad) * math.sin(theta) * math.cos(inc))
        sat_z = radius_km * math.sin(theta) * math.sin(inc)

        dec_rad = math.radians(solar_lat_deg)
        ra_rad = math.radians(sun_ra_deg)
        sun_ux = math.cos(dec_rad) * math.cos(ra_rad)
        sun_uy = math.cos(dec_rad) * math.sin(ra_rad)
        sun_uz = math.sin(dec_rad)

        sun_proj_km = sat_x * sun_ux + sat_y * sun_uy + sat_z * sun_uz
        perp_dist_km = math.sqrt(max(radius_km ** 2 - sun_proj_km ** 2, 0.0))

        # "eclipse"-сценарій імітує довшу тіньову ділянку (напр. інша пора року) -
        # трохи ширший ефективний радіус тіні замість штучного кутового порогу.
        shadow_radius_km = cfg.earth_radius_km * (1.08 if sc.key == "eclipse" else 1.0)
        in_shadow = sun_proj_km < 0.0 and perp_dist_km < shadow_radius_km

        visibility = "eclipsed" if in_shadow else "daylight"
        daylight_factor = 1.0 if visibility == "daylight" else 0.0

        # Synthetic surface weather below the satellite.
        solar_factor = max(math.cos(math.radians(sun_sep_deg)), 0.0)
        seasonal = 10.0 * math.sin(2.0 * math.pi * (doy - 172.0) / 365.2422)
        longitude_wave = 6.0 * math.sin(math.radians(longitude_deg * 1.8) + 0.00085 * t)
        lat_cooling = 0.47 * abs(latitude_deg)

        surface_target = 31.0 * solar_factor + seasonal + longitude_wave - lat_cooling + 4.0
        self.surface_temp_c = phase_smooth(self.surface_temp_c, clamp(surface_target, -50.0, 44.0), 0.15, 0.14,
                                           rng=self.rng)

        wind_target = 10.0 + 24.0 * abs(math.sin(math.radians(latitude_deg * 1.6)))
        wind_target += 8.0 * self.cloud_cover_pct / 100.0
        if sc.key == "geomagnetic":
            wind_target += 1.5 * math.sin(0.004 * t)
        self.wind_speed_kmh = clamp(phase_smooth(self.wind_speed_kmh, wind_target, 0.14, 0.35, rng=self.rng), 0.0,
                                    82.0)

        cloud_target = 42.0 + 30.0 * math.sin(0.00082 * t + math.radians(longitude_deg * 0.9))
        cloud_target += 16.0 * math.cos(math.radians(latitude_deg * 1.25))
        cloud_target += 10.0 * (1.0 - solar_factor)
        self.cloud_cover_pct = clamp(
            phase_smooth(self.cloud_cover_pct, clamp(cloud_target, 0.0, 100.0), 0.13, 0.7, rng=self.rng), 0.0, 100.0)

        # Onboard environment.
        crew_cycle = 0.5 + 0.5 * math.sin(2.0 * math.pi * (utc_hours - 6.0) / 24.0)
        experiment_load = 0.5 + 0.5 * math.sin(0.0013 * t + 1.7)
        thermal_load = 0.40 * daylight_factor + 0.35 * experiment_load + 0.20 * crew_cycle

        temp_target = 22.8 + 1.0 * thermal_load + 0.45 * math.sin(0.0009 * t + 0.3) + sc.thermal_bias_c
        self.cabin_temp_c = clamp(
            phase_smooth(self.cabin_temp_c, clamp(temp_target, 20.8, 29.5), 0.13, 0.025, rng=self.rng), 20.5, 30.0)

        humidity_target = 43.0 + 8.5 * crew_cycle + 3.0 * math.sin(0.0011 * t + 1.0) + sc.humidity_bias
        humidity_target -= 0.9 * (self.cabin_temp_c - 23.0)
        self.cabin_humidity_pct = clamp(
            phase_smooth(self.cabin_humidity_pct, clamp(humidity_target, 28.0, 72.0), 0.13, 0.10, rng=self.rng),
            24.0, 75.0)

        pressure_target = 14.70 + 0.04 * math.sin(0.00045 * t + 2.3) + sc.pressure_bias
        self.cabin_pressure_psi = clamp(
            phase_smooth(self.cabin_pressure_psi, pressure_target, 0.10, 0.0025, rng=self.rng), 14.45, 14.98)

        co2_target = 2.8 + 1.05 * crew_cycle + 0.75 * experiment_load + sc.co2_bias
        co2_target += 0.32 * max(0.0, math.sin(0.0023 * t + 2.1))
        self.co2_mmhg = clamp(
            phase_smooth(self.co2_mmhg, clamp(co2_target, 1.8, 7.4), 0.16, 0.018, rng=self.rng), 1.6, 7.8)

        o2_target = 159.3 - 0.50 * (self.co2_mmhg - 3.2) + 0.7 * math.sin(0.0007 * t + 1.9)
        self.o2_mmhg = clamp(
            phase_smooth(self.o2_mmhg, clamp(o2_target, 153.5, 164.5), 0.13, 0.025, rng=self.rng), 153.0, 165.0)

        # Energy model.
        if visibility == "daylight":
            solar_target = 94.0 + 18.0 * math.sin(math.radians(latitude_deg * 0.8) + 0.8)
            solar_target += 8.0 * math.sin(0.0010 * t + 0.4)
            solar_target *= sc.solar_power_multiplier
        else:
            solar_target = 23.0 + 8.0 * math.sin(0.0013 * t + 0.9)
            solar_target *= sc.eclipse_power_multiplier

        self.solar_power_kw = clamp(
            phase_smooth(self.solar_power_kw, clamp(solar_target, 2.0, 124.0), 0.18, 0.22, rng=self.rng), 0.0, 128.0)

        station_load_kw = 72.0 + 8.0 * crew_cycle + 5.5 * experiment_load
        if sc.key == "thermal":
            station_load_kw += 5.0
        if sc.key == "debris" and (int(t) // 120) % 10 == 0:
            station_load_kw += 7.0

        self.power_balance_kw = self.solar_power_kw - station_load_kw
        self.battery_soc_pct = clamp(
            self.battery_soc_pct + (self.power_balance_kw / cfg.station_battery_capacity_kWh) * (dt / 60.0),
            8.0, 100.0)

        # Space weather / communication.
        if sc.key == "geomagnetic":
            kp_target = 6.5 + 1.2 * math.sin(0.004 * t)
        elif sc.key == "solar_flare":
            kp_target = 5.0 + 0.8 * math.sin(0.002 * t + 2.0)
        else:
            kp_target = 2.2 + 0.8 * math.sin(0.0007 * t + 0.4)

        self.geomagnetic_kp = phase_smooth(self.geomagnetic_kp, clamp(kp_target, 0.0, 9.0), 0.15, 0.04, rng=self.rng)

        south_atlantic_factor = 1.0 if -55 < latitude_deg < 5 and -90 < longitude_deg < -20 else 0.0
        polar_factor = clamp((abs(latitude_deg) - 45.0) / 8.0, 0.0, 1.0)
        radiation_target = 8.0 + 5.0 * polar_factor + 18.0 * south_atlantic_factor
        radiation_target += 4.0 * max(0.0, self.geomagnetic_kp - 4.0)
        radiation_target *= sc.radiation_multiplier
        radiation_target += sc.radiation_spike * max(0.0, math.sin(0.0035 * t + 1.0))
        self.radiation_index = clamp(
            phase_smooth(self.radiation_index, clamp(radiation_target, 3.0, 100.0), 0.18, 0.35, rng=self.rng),
            0.0, 100.0)

        comm_target = 97.0 - 0.18 * self.radiation_index - 3.5 * max(0.0, self.geomagnetic_kp - 5.0)
        comm_target += sc.comm_quality_bias
        if self.rng.random() < sc.comm_drop_chance:
            comm_target -= self.rng.uniform(12.0, 35.0)
        self.comm_quality_pct = clamp(
            phase_smooth(self.comm_quality_pct, clamp(comm_target, 0.0, 100.0), 0.20, 0.55, rng=self.rng), 0.0, 100.0)

        # Attitude / maneuver model.
        maneuver_active = False
        if sc.key == "debris":
            cycle = t % 900.0
            maneuver_active = 80.0 < cycle < 190.0

        attitude_target = 0.035 + 0.04 * math.sin(0.003 * t)
        if maneuver_active:
            attitude_target += 0.32 + 0.10 * math.sin(0.04 * t)
            self.delta_v_total_ms += sc.maneuver_delta_v_ms * dt / 130.0
        attitude_target += sc.control_jitter * abs(self.rng.gauss(0.0, 0.25))
        self.attitude_error_deg = phase_smooth(self.attitude_error_deg, clamp(attitude_target, 0.0, 1.4), 0.22, 0.006,
                                               rng=self.rng)

        # Scientific-ish health scores.
        # NOTE: cfg.co2_limit_mmhg / cfg.cabin_pressure_tolerance_psi (NASA short-term limits)
        # свідомо НЕ підставлені напряму в сигми нижче - це змінило б чутливість
        # system_status (NOMINAL/WATCH/ALERT/CRITICAL) і зламало б відкалібровану поведінку
        # демо-сценаріїв. Використовуйте їх для окремого, явного "compliance"-індикатора,
        # а не для заміни існуючих gauss_score сигм без окремого регресійного тестування.
        temp_ok = gauss_score(self.cabin_temp_c, 23.8, 1.45)
        hum_ok = gauss_score(self.cabin_humidity_pct, 47.0, 10.5)
        pressure_ok = gauss_score(self.cabin_pressure_psi, 14.70, 0.08)
        co2_ok = gauss_score(self.co2_mmhg, 3.1, 1.15)
        o2_ok = gauss_score(self.o2_mmhg, 159.0, 2.0)

        life_support_score = clamp(
            100.0 * (0.25 * temp_ok + 0.16 * hum_ok + 0.23 * pressure_ok + 0.18 * co2_ok + 0.18 * o2_ok), 0.0, 100.0)

        alt_ok = gauss_score(altitude_km, 419.0, 7.2)
        vel_ok = gauss_score(velocity_kmh, 27570.0, 78.0)
        period_ok = gauss_score(orbital_period_min, 92.68, 0.62)
        attitude_ok = gauss_score(self.attitude_error_deg, 0.05, 0.32)
        orbit_score = clamp(100.0 * (0.34 * alt_ok + 0.28 * vel_ok + 0.22 * period_ok + 0.16 * attitude_ok), 0.0, 100.0)

        power_score = clamp(100.0 * (
                0.52 * gauss_score(self.battery_soc_pct, 88.0, 19.0)
                + 0.30 * gauss_score(self.solar_power_kw, 88.0, 42.0)
                + 0.18 * gauss_score(self.power_balance_kw, 5.0, 45.0)
        ), 0.0, 100.0)

        comm_score = clamp(self.comm_quality_pct, 0.0, 100.0)
        radiation_score = clamp(100.0 - self.radiation_index * 1.18, 0.0, 100.0)

        mission_score = clamp(
            0.28 * life_support_score
            + 0.24 * orbit_score
            + 0.18 * power_score
            + 0.15 * comm_score
            + 0.15 * radiation_score,
            0.0,
            100.0,
        )

        if mission_score >= 82.0:
            system_status = "NOMINAL"
        elif mission_score >= 65.0:
            system_status = "WATCH"
        elif mission_score >= 45.0:
            system_status = "ALERT"
        else:
            system_status = "CRITICAL"

        event_message = self._build_event_message(sc, system_status, maneuver_active)

        sample = SatelliteTelemetry(
            utc_time=now_sim.strftime("%Y-%m-%d %H:%M:%S UTC"),
            t_sim_s=t,
            scenario=sc.key,
            latitude_deg=latitude_deg,
            longitude_deg=longitude_deg,
            altitude_km=altitude_km,
            velocity_kmh=velocity_kmh,
            velocity_ms=velocity_ms,
            orbital_period_min=orbital_period_min,
            footprint_km=footprint_km,
            visibility=visibility,
            solar_lat_deg=solar_lat_deg,
            solar_lon_deg=solar_lon_deg,
            cabin_temp_c=self.cabin_temp_c,
            cabin_humidity_pct=self.cabin_humidity_pct,
            cabin_pressure_psi=self.cabin_pressure_psi,
            co2_mmhg=self.co2_mmhg,
            o2_mmhg=self.o2_mmhg,
            solar_power_kw=self.solar_power_kw,
            battery_soc_pct=self.battery_soc_pct,
            power_balance_kw=self.power_balance_kw,
            radiation_index=self.radiation_index,
            geomagnetic_kp=self.geomagnetic_kp,
            comm_quality_pct=self.comm_quality_pct,
            attitude_error_deg=self.attitude_error_deg,
            delta_v_ms=self.delta_v_total_ms,
            surface_temp_c=self.surface_temp_c,
            wind_speed_kmh=self.wind_speed_kmh,
            cloud_cover_pct=self.cloud_cover_pct,
            life_support_score=life_support_score,
            orbit_score=orbit_score,
            power_score=power_score,
            comm_score=comm_score,
            radiation_score=radiation_score,
            mission_score=mission_score,
            system_status=system_status,
            event_message=event_message,
        )
        self.last_sample = sample
        return sample

    @staticmethod
    def _build_event_message(sc: SatelliteScenario, status: str, maneuver_active: bool) -> str:
        if maneuver_active:
            return "DEBRIS AVOIDANCE BURN - short maneuver impulse, attitude correction active"
        if sc.key == "geomagnetic":
            return "GEOMAGNETIC STORM - Kp elevated, radiation and communication margins reduced"
        if sc.key == "solar_flare":
            return "SOLAR FLARE - radiation monitor rising, comm link may become unstable"
        if sc.key == "drag":
            return "ATMOSPHERIC DRAG - slow orbital altitude decay, reboost planning recommended"
        if sc.key == "blackout":
            return "COMMUNICATION BLACKOUT - telemetry link intermittent, onboard systems still simulated"
        if sc.key == "eclipse":
            return "ECLIPSE POWER SAVING - solar generation low, battery discharge visible"
        if sc.key == "thermal":
            return "THERMAL CONTROL ANOMALY - cabin environment drifting from ideal band"
        if status == "NOMINAL":
            return "NOMINAL OPERATIONS - all synthetic telemetry groups remain within expected limits"
        return "MISSION WATCH - one or more synthetic telemetry groups require monitoring"


# ============================================================
#  DRONE / UAV THERMAL-ELECTRIC SIMULATION
# ============================================================


@dataclass
class DroneConfig:
    Imax: float = 45.0
    Tmax: float = 90.0

    dt: float = 0.05
    ambient_temp: float = 26.0

    winding_resistance: float = 0.060
    thermal_capacity: float = 58.0
    cooling_tau: float = 42.0
    # Частка споживаної електричної потужності (V*I), яка йде в корисну механічну
    # роботу гвинта, а НЕ в тепло. Типово 0.85-0.90 для здорового BLDC-мотора+ESC
    # на крейсерському режимі. Використовується в новій моделі heat_power = V*I*(1-η).
    mechanical_efficiency: float = 0.86

    min_current: float = 3.0
    cruise_current: float = 20.0
    max_rate_change_A_per_s: float = 12.0
    current_sensor_noise: float = 0.22
    temp_sensor_noise: float = 0.035

    nominal_voltage: float = 22.2
    full_voltage: float = 25.2
    internal_resistance: float = 0.030
    battery_capacity_Ah: float = 6.0
    motor_kv: float = 920.0

    temp_weight: float = 0.60
    current_weight: float = 0.40


@dataclass
class DroneTelemetry:
    t: float
    scenario: str
    Tcurrent: float
    Icurrent: float
    risk: float
    status: str
    mission_phase: str

    heat_power_W: float
    heat_energy_J: float
    electrical_power_W: float

    voltage_V: float
    battery_soc_percent: float
    rpm: float
    throttle_percent: float
    horizontal_speed_kmh: float

    magnet_health_percent: float
    demag_risk: float
    thermal_margin_C: float

    cooling_rate_C_per_s: float
    heating_rate_C_per_s: float
    efficiency_percent: float

    def to_dict(self) -> dict:
        return asdict(self)


DRONE_SCENARIOS = ["Normal mission", "Hot day", "Wind gusts", "Payload stress", "Emergency test"]


def status_from_drone_risk(k: float) -> str:
    if k <= 0.40:
        return "SAFE"
    if k <= 0.75:
        return "CAUTION"
    return "DANGER"


def calculate_drone_risk(Tcurrent: float, Icurrent: float, rpm: float, voltage: float, cfg: DroneConfig) -> float:
    t_norm = clamp(Tcurrent / cfg.Tmax, 0.0, 1.35)
    thermal_part = cfg.temp_weight * (t_norm ** 2.25)

    # Очікувані оберти на цій напрузі за майже повного газу - опорна точка
    # "здорового" мотора. Якщо реальні оберти суттєво нижчі за очікувані,
    # а струм при цьому високий - це ознака розмагнічування ротора
    # (мотор споживає струм, але не видає механічну роботу/оберти).
    expected_rpm = voltage * cfg.motor_kv * 0.9
    actual_rpm_ratio = clamp(rpm / max(expected_rpm, 1.0), 0.0, 1.0)
    current_ratio = clamp(Icurrent / cfg.Imax, 0.0, 1.0)

    divergence = max(0.0, current_ratio - actual_rpm_ratio)
    divergence_part = cfg.current_weight * divergence * 1.5

    return clamp(thermal_part + divergence_part, 0.0, 1.0)


class MissionProfile:
    def __init__(self, cfg: DroneConfig):
        self.cfg = cfg
        self.phase_name = "BOOT"
        self.phase_until = 0.0
        self.phase_target_current = cfg.cruise_current
        self.burst_until = 0.0
        self.burst_extra_current = 0.0
        self.scenario_name = "Normal mission"

        self.phases = [
            ("IDLE / SENSOR CHECK", 5.0, 10.0, 7.0),
            ("STABLE HOVER", 13.0, 22.0, 12.0),
            ("CRUISE", 18.0, 29.0, 16.0),
            ("CLIMB", 27.0, 36.0, 10.0),
            ("PAYLOAD / WIND LOAD", 30.0, 41.0, 9.0),
            ("RECOVERY COOLING", 8.0, 17.0, 10.0),
        ]

    def set_scenario(self, name: str) -> None:
        self.scenario_name = name if name in DRONE_SCENARIOS else "Normal mission"
        self.phase_until = 0.0
        self.burst_until = 0.0
        self.burst_extra_current = 0.0

    def scenario_params(self) -> Dict[str, float]:
        presets = {
            "Normal mission": {"current_multiplier": 1.00, "burst_chance": 0.020, "burst_min": 2.0, "burst_max": 7.0,
                               "wind_wave": 0.7},
            "Hot day": {"current_multiplier": 1.03, "burst_chance": 0.020, "burst_min": 3.0, "burst_max": 7.5,
                        "wind_wave": 0.8},
            "Wind gusts": {"current_multiplier": 1.08, "burst_chance": 0.050, "burst_min": 4.0, "burst_max": 10.0,
                           "wind_wave": 2.4},
            "Payload stress": {"current_multiplier": 1.17, "burst_chance": 0.045, "burst_min": 5.0, "burst_max": 11.0,
                               "wind_wave": 1.5},
            "Emergency test": {"current_multiplier": 1.30, "burst_chance": 0.070, "burst_min": 6.0, "burst_max": 13.0,
                               "wind_wave": 2.0},
        }
        return presets.get(self.scenario_name, presets["Normal mission"])

    def next_target_current(self, t: float, temperature: float) -> Tuple[float, str]:
        p = self.scenario_params()

        if t >= self.phase_until:
            name, low, high, avg_duration = random.choice(self.phases)
            self.phase_name = name
            self.phase_target_current = random.uniform(low, high)
            self.phase_until = t + random.uniform(avg_duration * 0.55, avg_duration * 1.55)

        if t >= self.burst_until and random.random() < p["burst_chance"]:
            self.burst_extra_current = random.uniform(p["burst_min"], p["burst_max"])
            self.burst_until = t + random.uniform(1.0, 4.5)

        burst = self.burst_extra_current if t < self.burst_until else 0.0
        wind_wave = (math.sin(t * 0.19) * 0.55 + math.sin(t * 0.047 + 1.3) * 0.45) * p["wind_wave"]

        thermal_derate = 0.0
        if temperature > 76.0:
            thermal_derate += (temperature - 76.0) * 0.55
        if temperature > 84.0:
            thermal_derate += (temperature - 84.0) * 1.40

        target = self.phase_target_current * p["current_multiplier"] + burst + wind_wave - thermal_derate
        return clamp(target, self.cfg.min_current, self.cfg.Imax * 1.03), self.phase_name


class DroneSimulator:
    def __init__(self, cfg: DroneConfig | None = None):
        self.cfg = cfg or DroneConfig()
        self.mission = MissionProfile(self.cfg)
        self.scenario_name = "Normal mission"
        self.reset()

    def reset(self) -> None:
        self.t = 0.0
        self.temperature = self.cfg.ambient_temp + random.uniform(2.0, 4.0)
        self.current = self.cfg.cruise_current + random.uniform(-1.0, 1.0)
        self.heat_energy = 0.0
        self.battery_soc = 100.0
        self.magnet_health = 100.0
        self.last_sample: DroneTelemetry | None = None

    def set_scenario(self, name: str) -> None:
        self.scenario_name = name if name in DRONE_SCENARIOS else "Normal mission"
        self.mission.set_scenario(self.scenario_name)

        if self.scenario_name == "Hot day":
            self.cfg.ambient_temp = 37.0
            self.cfg.cooling_tau = 55.0
        elif self.scenario_name == "Wind gusts":
            self.cfg.ambient_temp = 28.0
            self.cfg.cooling_tau = 46.0
        elif self.scenario_name == "Payload stress":
            self.cfg.ambient_temp = 30.0
            self.cfg.cooling_tau = 50.0
        elif self.scenario_name == "Emergency test":
            self.cfg.ambient_temp = 32.0
            self.cfg.cooling_tau = 60.0
        else:
            self.cfg.ambient_temp = 26.0
            self.cfg.cooling_tau = 42.0

        self.reset()

    def estimate_voltage(self, Icurrent: float) -> float:
        soc_part = clamp(self.battery_soc / 100.0, 0.0, 1.0)
        open_voltage = self.cfg.nominal_voltage + (self.cfg.full_voltage - self.cfg.nominal_voltage) * soc_part
        voltage = open_voltage - Icurrent * self.cfg.internal_resistance
        return clamp(voltage, self.cfg.nominal_voltage * 0.68, self.cfg.full_voltage)

    def update_battery(self, voltage: float, current: float, dt: float) -> None:
        used_Wh = voltage * current * dt / 3600.0
        capacity_Wh = self.cfg.nominal_voltage * self.cfg.battery_capacity_Ah
        self.battery_soc = clamp(self.battery_soc - (used_Wh / capacity_Wh) * 100.0, 0.0, 100.0)

    def update_magnet_health(self, Tcurrent: float, Icurrent: float, dt: float) -> None:
        if Tcurrent < 82.0:
            self.magnet_health += 0.002 * dt
        else:
            temp_stress = ((Tcurrent - 82.0) / 8.0) ** 2
            current_stress = (Icurrent / self.cfg.Imax) ** 1.4
            damage_rate = 0.035 * temp_stress * current_stress
            self.magnet_health -= damage_rate * dt
        self.magnet_health = clamp(self.magnet_health, 0.0, 100.0)

    def step(self) -> DroneTelemetry:
        cfg = self.cfg
        dt = cfg.dt
        self.t += dt

        # ==========================================================
        # === ІНТЕГРОВАНО: РЕАЛІСТИЧНЕ ЗНЕСТРУМЛЕННЯ (BLACKOUT) ===
        # ==========================================================
        if self.battery_soc <= 0.0:
            self.battery_soc = 0.0

            # Електричні метрики в нуль
            self.current = 0.0
            Icurrent = 0.0
            voltage = 0.0
            heat_power = 0.0
            heating_rate = 0.0

            # Прискорене експоненційне охолодження прямо до 0°C
            cooling_rate = self.temperature * 0.15
            self.temperature = max(0.0, self.temperature - cooling_rate * dt)
            Tcurrent = self.temperature

            # Інерційне згасання обертів на основі попереднього кадру
            rpm = 0.0
            if self.last_sample:
                rpm = max(0.0, self.last_sample.rpm - 2500.0 * dt)
            horizontal_speed_kmh = max(0.0, (rpm / 15000.0) * 67.0)

            # Обнулення ризиків та ефективності системи
            risk = 0.0
            status = "SAFE (OFFLINE)"
            efficiency = 0.0
            demag_risk = 0.0
            thermal_margin = cfg.Tmax - Tcurrent

            sample = DroneTelemetry(
                t=self.t,
                scenario=self.scenario_name,
                Tcurrent=Tcurrent,
                Icurrent=Icurrent,
                risk=risk,
                status=status,
                mission_phase="SYSTEM SHUTDOWN",
                heat_power_W=heat_power,
                heat_energy_J=self.heat_energy,
                electrical_power_W=0.0,
                voltage_V=voltage,
                battery_soc_percent=0.0,
                rpm=rpm,
                horizontal_speed_kmh=horizontal_speed_kmh,
                throttle_percent=0.0,
                magnet_health_percent=self.magnet_health,
                demag_risk=demag_risk,
                thermal_margin_C=thermal_margin,
                cooling_rate_C_per_s=cooling_rate,
                heating_rate_C_per_s=heating_rate,
                efficiency_percent=efficiency,
            )
            self.last_sample = sample
            return sample
        # ==========================================================

        target_current, phase = self.mission.next_target_current(self.t, self.temperature)

        natural_delta = (target_current - self.current) * 0.14 + random.gauss(0.0, 0.12)
        max_delta = cfg.max_rate_change_A_per_s * dt
        self.current = clamp(self.current + clamp(natural_delta, -max_delta, max_delta), 0.0, cfg.Imax * 1.05)

        Icurrent = clamp(self.current + random.gauss(0.0, cfg.current_sensor_noise), 0.0, cfg.Imax * 1.08)

        # Напруга потрібна тут, ще до розрахунку теплової потужності (нижче).
        voltage = self.estimate_voltage(Icurrent)

        # Electrical power P = V * I (уся споживана потужність), з якої частка
        # dynamic_efficiency йде в корисну механічну роботу гвинта, а решта - в тепло.
        # ККД тепер динамічний: деградовані магніти (magnet_health) не дають
        # мотору ефективно перетворювати струм в обертовий момент, тому більша
        # частка енергії йде саме в тепло, а не в корисну роботу.
        electrical_power = voltage * Icurrent
        dynamic_efficiency = cfg.mechanical_efficiency * (self.magnet_health / 100.0)
        heat_power = electrical_power * (1.0 - dynamic_efficiency)

        self.heat_energy += heat_power * dt

        heating_rate = heat_power / cfg.thermal_capacity
        cooling_rate = (self.temperature - cfg.ambient_temp) / cfg.cooling_tau
        esc_extra_heat = 0.006 * max(0.0, Icurrent - 24.0)

        dT = (heating_rate - cooling_rate + esc_extra_heat) * dt + random.gauss(0.0, cfg.temp_sensor_noise)
        self.temperature = clamp(self.temperature + dT, cfg.ambient_temp - 1.0, cfg.Tmax + 15.0)
        Tcurrent = self.temperature

        self.update_battery(voltage, Icurrent, dt)
        self.update_magnet_health(Tcurrent, Icurrent, dt)

        throttle = clamp(Icurrent / cfg.Imax, 0.0, 1.0)
        heat_derate = 1.0
        if Tcurrent > 80.0:
            heat_derate -= clamp((Tcurrent - 80.0) / 28.0, 0.0, 0.25)

        # Ідеальні оберти, які контролер ХОЧЕ отримати за поточного струму/напруги.
        rpm_ideal = voltage * cfg.motor_kv * (0.16 + 0.84 * throttle)

        # РЕАЛЬНІ оберти падають пропорційно деградації магнітів (magnet_health),
        # навіть якщо струм максимальний - саме так виникає розбіжність
        # "струм росте, а оберти падають" при перегріві/розмагнічуванні.
        rpm = rpm_ideal * (self.magnet_health / 100.0) * heat_derate + random.gauss(0.0, 45.0)
        rpm = max(0.0, rpm)

        # Horizontal speed depends on RPM (8-75 km/h range)
        horizontal_speed_kmh = 8.0 + (rpm / 15000.0) * 67.0
        horizontal_speed_kmh = clamp(horizontal_speed_kmh, 5.0, 75.0)

        risk = calculate_drone_risk(Tcurrent, Icurrent, rpm, voltage, cfg)
        status = status_from_drone_risk(risk)

        demag_risk = clamp((Tcurrent - 70.0) / max(1.0, cfg.Tmax - 70.0), 0.0, 1.0) ** 2
        thermal_margin = cfg.Tmax - Tcurrent

        # Теплова частка тепер ДОМІНУЄ над throttle: рахуємо, наскільки Tcurrent
        # наблизилась до Tmax (0 - холодний мотор, 1 - точно на межі Tmax),
        # і беремо це в квадрат, щоб штраф різко зростав саме біля перегріву.
        # Завдяки цьому ефективність падає слідом за температурою навіть тоді,
        # коли throttle вже скинутий (через теплову інерцію мотор ще гарячий).
        temp_ratio = clamp((Tcurrent - 40.0) / (cfg.Tmax - 40.0), 0.0, 1.4)

        efficiency = 100.0
        efficiency -= 45.0 * temp_ratio ** 2
        efficiency -= 6.0 * throttle ** 2
        efficiency -= 5.0 * (1.0 - self.magnet_health / 100.0)
        efficiency = clamp(efficiency, 20.0, 100.0)

        sample = DroneTelemetry(
            t=self.t,
            scenario=self.scenario_name,
            Tcurrent=Tcurrent,
            Icurrent=Icurrent,
            risk=risk,
            status=status,
            mission_phase=phase,
            heat_power_W=heat_power,
            heat_energy_J=self.heat_energy,
            electrical_power_W=electrical_power,
            voltage_V=voltage,
            battery_soc_percent=self.battery_soc,
            rpm=rpm,
            horizontal_speed_kmh=horizontal_speed_kmh,
            throttle_percent=throttle * 100.0,
            magnet_health_percent=self.magnet_health,
            demag_risk=demag_risk,
            thermal_margin_C=thermal_margin,
            cooling_rate_C_per_s=cooling_rate,
            heating_rate_C_per_s=heating_rate,
            efficiency_percent=efficiency,
        )
        self.last_sample = sample
        return sample


def simulation_meta() -> dict:
    return {
        "satellite_scenarios": [asdict(s) for s in SATELLITE_SCENARIOS],
        "drone_scenarios": DRONE_SCENARIOS,
    }
    
