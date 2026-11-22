"""Constants for the HA Virtual Boiler Water Meter integration."""

DOMAIN = "ha_virtual_boiler_water_meter"

# Configuration fields
CONF_SOURCE_TYPE = "source_type"  # "power" | "energy"
CONF_SOURCE_SENSOR = "source_sensor"  # power sensor (W/kW) or energy sensor (Wh/kWh)
CONF_TANK_TEMP_SENSOR = "tank_temp_sensor"  # entity_id or empty
CONF_TANK_TEMP_CONST = "tank_temp_const"  # fallback constant, degC
CONF_COLD_TEMP_SENSOR = "cold_temp_sensor"  # entity_id or empty
CONF_COLD_TEMP_CONST = "cold_temp_const"  # degC
CONF_STANDBY_LOSS = "standby_loss"  # Wh per day (0 = disabled)
CONF_COP = "cop"  # 1.0 resistive, 2-3 thermodynamic
CONF_CALIBRATION = "calibration"  # multiplicative factor, default 1.0

DEFAULT_TANK_TEMP = 45.0
DEFAULT_COLD_TEMP = 13.0
DEFAULT_STANDBY_LOSS = 0.0
DEFAULT_COP = 1.0
DEFAULT_CALIBRATION = 1.0

# Physics: 1 litre of water raised by 1 degC needs 1.163 Wh
WH_PER_LITRE_PER_DEGC = 1.163

WATER_SPECIFIC_HEAT = WH_PER_LITRE_PER_DEGC
