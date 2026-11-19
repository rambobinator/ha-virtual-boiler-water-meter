"""Sensor platform: estimate hot water volume from heating energy via thermal balance."""

from __future__ import annotations

import logging
from typing import Any, Optional

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


def _power_unit_to_wh_per_hour(unit: str) -> Optional[float]:
    """Return Wh per hour for a power unit, i.e. Wh for 1 hour at 1 unit."""
    unit = unit.lower()
    if unit in ("w", "watt"):
        return 1.0
    if unit in ("kw", "kilowatt"):
        return 1000.0
    return None


def _energy_unit_to_wh(unit: str) -> Optional[float]:
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
    """Estimate hot water volume (m3) from heating energy and thermal balance."""

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

        # cumulative energy, Wh (for power sources)
        self._energy_wh: float = 0.0
        self._last_power: Optional[float] = None
        self._last_power_time: Any = None
        # cumulative standby allowance, Wh
        self._standby_allowance_wh: float = 0.0
        self._last_time: Any = None

        self._attr_name = self._name

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # restore internal accumulators after a restart
        if (last_state := await self.async_get_last_state()) is not None:
            saved = last_state.attributes.get("energy_wh")
            if saved is not None:
                self._energy_wh = float(saved)
            saved = last_state.attributes.get("standby_allowance_wh")
            if saved is not None:
                self._standby_allowance_wh = float(saved)
        self._last_time = dt_util.utcnow()
        # initialize from the current source value if it is an energy counter
        cur = self._hass.states.get(self._source)
        if cur is not None and self._source_type == "energy":
            try:
                factor = _energy_unit_to_wh(cur.attributes.get("unit_of_measurement", "kWh")) or 1.0
                self._energy_wh = float(cur.state) * factor
            except (TypeError, ValueError):
                pass
        self._compute()

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
            "energy_wh": round(self._energy_wh, 2),
            "standby_allowance_wh": round(self._standby_allowance_wh, 2),
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

    # --- main computation ---------------------------------------------
    def _compute(self) -> None:
        """Recompute native value (m3) from accumulated energy."""
        tank = self._tank_temp()
        cold = self._cold_temp()
        d_t = tank - cold
        
        # Guard against invalid temperature configurations
        if d_t <= 0:
            _LOGGER.warning(
                "Tank temperature (%.1f°C) ≤ cold water temperature (%.1f°C). "
                "Assuming 1°C minimum delta.",
                tank,
                cold,
            )
            d_t = 1.0
        
        useful_wh = self._energy_wh - self._standby_allowance_wh
        useful_wh = max(useful_wh, 0.0)
        # COP: heat delivered (Wh) = electrical Wh * COP
        heat_wh = useful_wh * self._cop
        litres = heat_wh / (WATER_SPECIFIC_HEAT * d_t) * self._calibration
        self._attr_native_value = round(max(litres, 0.0) / 1000.0, 4)

    @callback
    def _on_source_change(self, event: Event) -> None:
        new_state: State | None = event.data.get("new_state")
        now = dt_util.utcnow()

        if new_state is None or new_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            self._last_power = None
            return

        self._update_standby_allowance(now)

        try:
            value = float(new_state.state)
        except (TypeError, ValueError):
            return

        if self._source_type == "energy":
            # source is a cumulative energy counter: adopt its value directly
            unit_str = new_state.attributes.get("unit_of_measurement", "kWh")
            factor = _energy_unit_to_wh(unit_str)
            if factor is None:
                _LOGGER.warning(
                    "Unknown energy unit '%s' for %s, defaulting to 1.0",
                    unit_str,
                    self._source,
                )
                factor = 1.0
            self._energy_wh = value * factor
            _LOGGER.debug(
                "Energy source updated: %.2f %s = %.2f Wh",
                value,
                unit_str,
                self._energy_wh,
            )
        else:
            # source is instantaneous power: integrate (left rule)
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
            if self._last_power is not None and self._last_power_time is not None:
                hours = (now - self._last_power_time).total_seconds() / 3600.0
                if 0 <= hours < 2.0:  # ignore huge gaps (restarts etc.)
                    energy_added = self._last_power * hours
                    self._energy_wh += energy_added
                    _LOGGER.debug(
                        "Integrated power: %.2f W × %.4f h = %.2f Wh (cumulative: %.2f Wh)",
                        self._last_power,
                        hours,
                        energy_added,
                        self._energy_wh,
                    )
                elif hours >= 2.0:
                    _LOGGER.warning(
                        "Large time gap (%.1f h) since last power reading, skipping integration",
                        hours,
                    )
            self._last_power = power_wh_per_hour
            self._last_power_time = now

        self._compute()
        self.async_write_ha_state()

    def _update_standby_allowance(self, now) -> None:
        """Accrue standby losses in Wh since startup (simple daily proration)."""
        if self._last_time is None:
            self._last_time = now
            return
        if self._standby_wh_per_day <= 0:
            self._last_time = now
            return
        days = (now - self._last_time).total_seconds() / 86400.0
        allowance_added = self._standby_wh_per_day * days
        self._standby_allowance_wh += allowance_added
        _LOGGER.debug(
            "Standby allowance: %.2f Wh/day × %.4f days = %.2f Wh (cumulative: %.2f Wh)",
            self._standby_wh_per_day,
            days,
            allowance_added,
            self._standby_allowance_wh,
        )
        self._last_time = now
