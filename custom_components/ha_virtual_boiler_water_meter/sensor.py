"""Sensor platform: estimate hot water volume from heating energy via thermal balance."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfVolume,
)
from homeassistant.core import (
    Event,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
import homeassistant.util.dt as dt_util

from .const import (
    CONF_CALIBRATION,
    CONF_COLD_TEMP_CONST,
    CONF_COLD_TEMP_SENSOR,
    CONF_COP,
    CONF_SOURCE_SENSOR,
    CONF_SOURCE_TYPE,
    CONF_STANDBY_LOSS,
    CONF_TANK_TEMP_CONST,
    CONF_TANK_TEMP_SENSOR,
    DEFAULT_COLD_TEMP,
    DEFAULT_TANK_TEMP,
    DOMAIN,
    WATER_SPECIFIC_HEAT,
)

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = None  # event driven

# Ignore intervals larger than this (restarts, source unavailability, etc.).
MAX_INTERVAL_SECONDS = 2 * 3600


def _power_unit_to_wh_per_hour(unit: str) -> float | None:
    """Return Wh per hour for a power unit, i.e. Wh for 1 hour at 1 unit."""
    unit = unit.lower()
    if unit in ("w", "watt"):
        return 1.0
    if unit in ("kw", "kilowatt"):
        return 1000.0
    return None


def _energy_unit_to_wh(unit: str) -> float | None:
    """Return Wh for an energy unit, i.e. Wh for 1 unit of energy."""
    unit = unit.lower()
    if unit in ("wh", "watt hour", "watthour", "watt-hour"):
        return 1.0
    if unit in ("kwh", "kw h", "kilowatt hour", "kilowatthour", "kilowatt-hour"):
        return 1000.0
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the estimator sensor from a config entry."""
    async_add_entities([HotWaterEstimatorSensor(hass, entry)])


class HotWaterEstimatorSensor(RestoreSensor):
    """Estimate hot water volume (m3) from heating energy and thermal balance.

    The volume is accumulated *incrementally*: each energy increment is converted
    to litres using the temperature delta valid at the moment of heating, then
    added to a dedicated accumulator that is never recomputed. This guarantees a
    monotonically increasing value, as required by ``total_increasing``.
    """

    _attr_device_class = SensorDeviceClass.WATER
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:water-boiler"
    _attr_has_entity_name = False

    def __init__(self, hass: HomeAssistant, entry) -> None:
        self._hass = hass
        self._entry = entry
        d = entry.data

        self._attr_unique_id = f"{entry.entry_id}_hot_water"
        self._name = "Eau chaude estimée"

        self._source_type = d.get(CONF_SOURCE_TYPE, "power")
        self._source: str = d[CONF_SOURCE_SENSOR]
        self._tank_sensor: str | None = d.get(CONF_TANK_TEMP_SENSOR) or None
        self._tank_const: float = float(d.get(CONF_TANK_TEMP_CONST, DEFAULT_TANK_TEMP))
        self._cold_sensor: str | None = d.get(CONF_COLD_TEMP_SENSOR) or None
        self._cold_const: float = float(d.get(CONF_COLD_TEMP_CONST, DEFAULT_COLD_TEMP))
        self._standby_wh_per_day: float = float(d.get(CONF_STANDBY_LOSS, 0.0))
        self._cop: float = float(d.get(CONF_COP, 1.0))
        self._calibration: float = float(d.get(CONF_CALIBRATION, 1.0))

        # The single source of truth: litres accumulated so far (monotonic).
        self._cumulative_litres: float = 0.0

        # Interval tracking for incremental integration.
        self._last_power: float | None = None  # Wh per hour, for power sources
        self._last_energy_wh: float | None = None  # counter anchor, for energy sources
        self._last_time: Any = None

        self._attr_name = self._name

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        # Restore the accumulator after a restart.
        if (last_state := await self.async_get_last_state()) is not None:
            restored = last_state.attributes.get("cumulative_litres")
            if restored is not None:
                try:
                    self._cumulative_litres = float(restored)
                except (TypeError, ValueError):
                    pass
            elif last_state.state not in (None, STATE_UNKNOWN, STATE_UNAVAILABLE):
                # Upgrade path from older versions without the attribute:
                # continue from the last reported m3 value.
                try:
                    self._cumulative_litres = float(last_state.state) * 1000.0
                except (TypeError, ValueError):
                    pass

        self._last_time = dt_util.utcnow()
        self._last_power = None

        # Anchor the energy counter so the first delta after (re)start is zero,
        # avoiding a spurious jump across downtime.
        cur = self._hass.states.get(self._source)
        if cur is not None and self._source_type == "energy":
            try:
                factor = (
                    _energy_unit_to_wh(cur.attributes.get("unit_of_measurement", "kWh"))
                    or 1.0
                )
                self._last_energy_wh = float(cur.state) * factor
            except (TypeError, ValueError):
                self._last_energy_wh = None

        self._attr_native_value = round(self._cumulative_litres / 1000.0, 4)

        async_track_state_change_event(
            self._hass, [self._source], self._on_source_change
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "HA Virtual Boiler Water Meter",
            "manufacturer": "HA Virtual Boiler Water Meter",
        }

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "source": self._source,
            "source_type": self._source_type,
            "tank_temperature": self._tank_temp(),
            "cold_temperature": self._cold_temp(),
            "cumulative_litres": round(self._cumulative_litres, 3),
            "cop": self._cop,
            "calibration": self._calibration,
        }

    # --- temperatures -------------------------------------------------
    def _tank_temp(self) -> float:
        if self._tank_sensor:
            state = self._hass.states.get(self._tank_sensor)
            if state and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                try:
                    # water_heater exposes current_temperature as attribute
                    val = state.attributes.get("current_temperature")
                    if val is None:
                        val = state.state
                    return float(val)
                except (TypeError, ValueError):
                    pass
        return self._tank_const

    def _cold_temp(self) -> float:
        if self._cold_sensor:
            state = self._hass.states.get(self._cold_sensor)
            if state and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                try:
                    return float(state.state)
                except (TypeError, ValueError):
                    pass
        return self._cold_const

    def _delta_t(self) -> float:
        """Current temperature delta, guarded against degenerate values."""
        tank = self._tank_temp()
        cold = self._cold_temp()
        d_t = tank - cold
        if d_t <= 0:
            _LOGGER.warning(
                "Tank temperature (%.1f°C) ≤ cold water temperature (%.1f°C). "
                "Assuming 1°C minimum delta.",
                tank,
                cold,
            )
            d_t = 1.0
        return d_t

    # --- incremental accumulation -------------------------------------
    @callback
    def _on_source_change(self, event: Event) -> None:
        new_state: State | None = event.data.get("new_state")
        now = dt_util.utcnow()

        if new_state is None or new_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            # Pause integration and reset anchors so we never integrate across the gap.
            self._last_power = None
            self._last_time = now
            return

        try:
            value = float(new_state.state)
        except (TypeError, ValueError):
            return

        interval_s = None
        if self._last_time is not None:
            interval_s = (now - self._last_time).total_seconds()

        # 1) Energy increment (Wh) over this interval.
        delta_wh = self._energy_increment(new_state, value, interval_s)

        # 2) Deduct standby losses accrued over the same interval (clamped at 0).
        if (
            delta_wh > 0
            and self._standby_wh_per_day > 0
            and interval_s is not None
            and 0 < interval_s < MAX_INTERVAL_SECONDS
        ):
            standby_wh = self._standby_wh_per_day * (interval_s / 86400.0)
            usable_wh = max(delta_wh - standby_wh, 0.0)
        else:
            usable_wh = max(delta_wh, 0.0)

        # 3) Convert only this increment to litres, using the *current* delta T.
        if usable_wh > 0:
            d_t = self._delta_t()
            heat_wh = usable_wh * self._cop
            delta_litres = heat_wh * self._calibration / (WATER_SPECIFIC_HEAT * d_t)
            self._cumulative_litres += delta_litres
            _LOGGER.debug(
                "ΔE=%.2f Wh usable, ΔT=%.1f°C → +%.3f L (total %.3f L)",
                usable_wh,
                d_t,
                delta_litres,
                self._cumulative_litres,
            )

        self._last_time = now
        self._attr_native_value = round(self._cumulative_litres / 1000.0, 4)
        self.async_write_ha_state()

    def _energy_increment(
        self, new_state: State, value: float, interval_s: float | None
    ) -> float:
        """Return the energy delta (Wh) for this update, per source type."""
        if self._source_type == "energy":
            unit_str = new_state.attributes.get("unit_of_measurement", "kWh")
            factor = _energy_unit_to_wh(unit_str)
            if factor is None:
                _LOGGER.warning(
                    "Unknown energy unit '%s' for %s, defaulting to 1.0",
                    unit_str,
                    self._source,
                )
                factor = 1.0
            current_wh = value * factor
            delta_wh = 0.0
            if self._last_energy_wh is not None:
                delta_wh = current_wh - self._last_energy_wh
                if delta_wh < 0:
                    # Counter reset: start accumulating again from here.
                    _LOGGER.debug(
                        "Energy counter reset detected (%.2f < %.2f Wh)",
                        current_wh,
                        self._last_energy_wh,
                    )
                    delta_wh = 0.0
            self._last_energy_wh = current_wh
            return delta_wh

        # Instantaneous power source: integrate with the left Riemann rule.
        unit_str = new_state.attributes.get("unit_of_measurement", "W")
        factor = _power_unit_to_wh_per_hour(unit_str)
        if factor is None:
            _LOGGER.warning(
                "Unknown power unit '%s' for %s, defaulting to 1.0",
                unit_str,
                self._source,
            )
            factor = 1.0
        power_wh_per_hour = value * factor

        delta_wh = 0.0
        if self._last_power is not None and interval_s is not None:
            hours = interval_s / 3600.0
            if 0 <= interval_s < MAX_INTERVAL_SECONDS:
                delta_wh = self._last_power * hours
            else:
                _LOGGER.warning(
                    "Large time gap (%.1f h) since last power reading, skipping integration",
                    hours,
                )
        self._last_power = power_wh_per_hour
        return delta_wh
