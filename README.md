# HA Virtual Boiler Water Meter

[🇫🇷 Version française](README.fr.md)

[Home Assistant](https://www.home-assistant.io/) integration that estimates **hot water consumption (in m³)** from the heating energy of a hot water tank, without a dedicated water meter. The generated entity can be directly used in the **Water** section of Home Assistant's Energy dashboard.

![Water flow in the Energy dashboard, with the estimated hot water as a tracked consumer](https://raw.githubusercontent.com/rambobinator/ha-virtual-boiler-water-meter/main/docs/energy-dashboard-water-flow.png)

*Example: the estimated hot water shown as a consumer in the Energy dashboard's water flow.*

## Principle

Heating 1 litre of water by 1 °C requires 1.163 Wh. The electrical heating energy, corrected for standby losses and COP, gives the volume of hot water drawn:

```
Volume (L) = (E_heating(Wh) − losses(Wh)) × COP ÷ (1.163 × (T_tank − T_cold_water)) × calibration
```

## Configuration

Fields provided in the configuration flow:

| Field | Role | Default |
|---|---|---|
| Source type | **Power** sensor (integration done by the add-on) or **cumulative energy** sensor | power |
| Source sensor | E.g. `sensor.water_heater_5_1min` | required |
| Tank temperature | Entity (sensor or `water_heater.*`) or constant | 45 °C |
| Cold water temperature | Entity or constant (adjust seasonally) | 13 °C |
| Standby losses | Wh/day, deduced from overnight decay (e.g. ~1 °C/h) | 0 |
| COP | 1 = resistive; 2–3 = heat pump | 1 |
| Calibration | Multiplicative factor after comparison with a real meter | 1 |

## Installation (Local Testing)

1. Copy the `custom_components/ha_virtual_boiler_water_meter/` folder to `/config/custom_components/` in Home Assistant.
2. Restart Home Assistant.
3. Settings → Devices and Services → **Create Integration** → search for "HA Virtual Boiler Water Meter".
4. Fill in the fields, then add the `sensor.virtual_hot_water_meter` entity to Dashboards → Energy → Water section.

For daily estimation, add to `configuration.yaml`:

```yaml
utility_meter:
  hot_water_meter_daily:
    source: sensor.virtual_hot_water_meter
    cycle: daily
```

## Accuracy and Limitations

- Typical accuracy: **±15–20 %** (estimated inlet temperature, tank stratification, loss smoothing).
- Designed for **resistive** water heaters; for heat pump tanks, set the COP (>1).
- Estimation is cumulative since installation; use `utility_meter` for time periods.
- Does not replace a physical water meter for billing purposes.

## License

MIT — use, modify, republish freely.
