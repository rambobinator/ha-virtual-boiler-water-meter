"""Config flow for the HA Virtual Boiler Water Meter integration."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
)
import voluptuous as vol

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
    DEFAULT_CALIBRATION,
    DEFAULT_COLD_TEMP,
    DEFAULT_COP,
    DEFAULT_STANDBY_LOSS,
    DEFAULT_TANK_TEMP,
    DOMAIN,
)

SOURCE_TYPES = ["power", "energy"]


def _optional_entity(key: str, user_input: dict):
    """Build an optional entity key, pre-filled via suggested_value.

    EntitySelector cannot be serialized with a non-entity ``default`` (e.g. an
    empty string), which triggers a 400 when the form is rendered. The official
    way to pre-fill an optional entity field is ``description.suggested_value``.
    """
    existing = user_input.get(key)
    if existing:
        return vol.Optional(key, description={"suggested_value": existing})
    return vol.Optional(key)


def _build_schema(user_input: dict, include_source: bool = True) -> vol.Schema:
    """Build configuration schema.

    Args:
        user_input: User input dictionary with current values
        include_source: If False, excludes source type and sensor (for options flow)
    """
    schema_dict = {}

    if include_source:
        schema_dict[vol.Required(
            CONF_SOURCE_TYPE, default=user_input.get(CONF_SOURCE_TYPE, "power")
        )] = SelectSelector(
            SelectSelectorConfig(
                options=SOURCE_TYPES,
                mode="dropdown",
            )
        )
        schema_dict[_optional_entity(CONF_SOURCE_SENSOR, user_input)] = EntitySelector(
            EntitySelectorConfig(domain="sensor", multiple=False)
        )

    schema_dict.update({
        _optional_entity(CONF_TANK_TEMP_SENSOR, user_input): EntitySelector(
            EntitySelectorConfig(domain=["sensor", "water_heater"], multiple=False)
        ),
        vol.Required(
            CONF_TANK_TEMP_CONST,
            default=user_input.get(CONF_TANK_TEMP_CONST, DEFAULT_TANK_TEMP),
        ): NumberSelector(
            NumberSelectorConfig(min=20, max=90, step=0.5, unit="°C")
        ),
        _optional_entity(CONF_COLD_TEMP_SENSOR, user_input): EntitySelector(
            EntitySelectorConfig(domain="sensor", multiple=False)
        ),
        vol.Required(
            CONF_COLD_TEMP_CONST,
            default=user_input.get(CONF_COLD_TEMP_CONST, DEFAULT_COLD_TEMP),
        ): NumberSelector(
            NumberSelectorConfig(min=0, max=30, step=0.5, unit="°C")
        ),
        vol.Required(
            CONF_STANDBY_LOSS,
            default=user_input.get(CONF_STANDBY_LOSS, DEFAULT_STANDBY_LOSS),
        ): NumberSelector(
            NumberSelectorConfig(min=0, max=5000, step=50, unit="Wh/day")
        ),
        vol.Required(
            CONF_COP, default=user_input.get(CONF_COP, DEFAULT_COP)
        ): NumberSelector(
            NumberSelectorConfig(min=0.5, max=6, step=0.1)
        ),
        vol.Required(
            CONF_CALIBRATION,
            default=user_input.get(CONF_CALIBRATION, DEFAULT_CALIBRATION),
        ): NumberSelector(
            NumberSelectorConfig(min=0.1, max=10, step=0.05)
        ),
    })

    return vol.Schema(schema_dict)


class HotWaterEstimatorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the HA Virtual Boiler Water Meter config flow."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            if not user_input.get(CONF_SOURCE_SENSOR):
                errors[CONF_SOURCE_SENSOR] = "missing_source"
            else:
                return self.async_create_entry(
                    title="Eau chaude estimée", data=user_input
                )
        return self.async_show_form(
            step_id="user", data_schema=_build_schema(user_input or {}), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return HotWaterEstimatorOptionsFlow(config_entry)


class HotWaterEstimatorOptionsFlow(config_entries.OptionsFlow):
    """Allow editing the parameters after creation."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Handle options editing.

        Source type and sensor are immutable after creation to avoid
        resetting accumulators. Other parameters can be adjusted anytime.
        """
        if user_input is not None:
            # Preserve immutable source configuration
            user_input[CONF_SOURCE_TYPE] = self.config_entry.data[CONF_SOURCE_TYPE]
            user_input[CONF_SOURCE_SENSOR] = self.config_entry.data[CONF_SOURCE_SENSOR]
            return self.async_create_entry(title="", data=user_input)

        # Build schema excluding source type/entity (immutable after creation)
        schema_dict = dict(self.config_entry.data)
        schema = _build_schema(schema_dict, include_source=False)

        return self.async_show_form(step_id="init", data_schema=schema)
