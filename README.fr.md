# HA Virtual Boiler Water Meter

[🇬🇧 English version](README.md)

Intégration [Home Assistant](https://www.home-assistant.io/) qui estime la **consommation d'eau chaude sanitaire (en m³)** à partir de l'énergie de chauffe du ballon d'eau chaude, sans compteur d'eau dédié. L'entité produite est directement utilisable dans la section **Eau** du tableau Énergie de Home Assistant.

## Principe

Chauffer 1 litre d'eau de 1 °C requiert 1,163 Wh. L'énergie électrique de chauffe, corrigée des pertes en veille et du COP, donne donc le volume d'eau chaude tiré :

```
Volume (L) = (E_chauffe(Wh) − pertes(Wh)) × COP ÷ (1,163 × (T_ballon − T_eau_froide)) × calibration
```

## Configuration

Champs proposés dans le flux de configuration :

| Champ | Rôle | Défaut |
|---|---|---|
| Type de source | Capteur de **puissance** (l'intégration fait l'intégrale) ou d'**énergie cumulée** | puissance |
| Capteur source | Ex. `sensor.chauffe_eau_5_1min` | obligatoire |
| Température du ballon | Entité (capteur ou `water_heater.*`) ou constante | 45 °C |
| Température d'eau froide | Entité ou constante (ajuster saisonnièrement) | 13 °C |
| Pertes en veille | Wh/jour, déduit de la décroissance nocturne (ex. ~1 °C/h) | 0 |
| COP | 1 = résistif ; 2–3 = thermodynamique | 1 |
| Calibration | Facteur multiplicatif après comparaison avec un vrai compteur | 1 |

## Installation (test local)

1. Copiez le dossier `custom_components/ha_virtual_boiler_water_meter/` dans `/config/custom_components/` de Home Assistant.
2. Redémarrez Home Assistant.
3. Paramètres → Appareils et services → **Ajouter une intégration** → cherchez « HA Virtual Boiler Water Meter ».
4. Renseignez les champs, puis ajoutez l'entité `sensor.compteur_virtuel_eau_chaude` dans Tableaux de bord → Énergie → section Eau.

Pour l'estimation journalière, ajoutez dans `configuration.yaml` :

```yaml
utility_meter:
  compteur_eau_chaude_journalier:
    source: sensor.compteur_virtuel_eau_chaude
    cycle: daily
```

## Précision et limites

- Précision typique : **±15–20 %** (température d'entrée estimée, stratification du ballon, lissage des pertes).
- Prévu pour un chauffe-eau **résistif** ; pour un ballon thermodynamique, renseignez le COP (>1).
- L'estimation est cumulative depuis l'installation ; utilisez `utility_meter` pour les périodes.
- Ne remplace pas un compteur d'eau physique pour un usage facturable.

## Licence

MIT — utilisez, modifiez, republiez librement.
