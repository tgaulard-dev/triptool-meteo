# triptool-meteo

Découpe les prévisions météo ouvertes en tuiles de 5° × 5° pour l'app iOS
[TripTool](https://triptool.app) : l'app ne télécharge que les tuiles de sa
zone (quelques centaines de Ko) au lieu des fichiers mondiaux ou européens
(plusieurs centaines de Mo par actualisation), et sans clé d'API pour AROME.

Format des tuiles : [FORMAT.md](FORMAT.md).

## Modèles

| Modèle | Source | Cycles | Statut |
|---|---|---|---|
| ECMWF IFS 0,25° | data.ecmwf.int (données ouvertes) | 00 et 12 UTC, jusqu'à H+240 | en place |
| ICON-EU 0,0625° | opendata.dwd.de | 00, 06, 12 et 18 UTC, jusqu'à H+120 | en place |
| AROME 0,01° | meteo.data.gouv.fr (paquets Météo-France) | toutes les 3 h, jusqu'à H+51 | en place |
| GFS 0,25° | noaa-gfs-bdp-pds (archive NOAA sur AWS) | 00, 06, 12 et 18 UTC, jusqu'à H+384 | en place |

## Fonctionnement

Le workflow [`.github/workflows/tuiles.yml`](.github/workflows/tuiles.yml)
vérifie chaque heure, pour chaque modèle, si un cycle plus récent que celui
publié est complet. Si oui : téléchargement des seuls champs utiles, découpe
en tuiles, envoi sur Cloudflare R2, puis mise à jour de `<modèle>/latest.json`
en dernier. Les deux derniers cycles de chaque modèle sont conservés.

| Modèle | Tuiles | Volume par cycle | Tuile moyenne | Durée (Mac) |
|---|---|---|---|---|
| ECMWF | 2 592 (monde) | ≈ 320 Mo | ≈ 125 Ko | ≈ 1 min 30 |
| ICON-EU | 180 (Europe) | ≈ 185 Mo | ≈ 1 Mo | ≈ 1 min |
| AROME | 551 (France, 1° × 1°) | ≈ 800 Mo | ≈ 1,5 Mo | ≈ 8 min (estimé) |
| GFS | 2 592 (monde) | à mesurer | à mesurer | à mesurer |

Secrets à définir dans le dépôt (Settings → Secrets and variables → Actions) :
`R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`.

## En local

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover tests
.venv/bin/python -m ttwx produce --out build --steps 0,3,48 --bbox 45,-10,50,0
.venv/bin/python tests/check_against_grib.py ecmwf build/ecmwf/<cycle> <cycle> 48
.venv/bin/python tests/check_arome.py build/arome/<cycle>/N48W005.ttwx <cycle> 12
```

`check_against_grib.py` compare les tuiles aux valeurs lues directement dans
le GRIB d'origine (coordonnées identiques, écart au plus l'arrondi du format).

## Sources et licences des données

- Météo-France : paquets AROME publiés sur meteo.data.gouv.fr, Licence
  Ouverte 2.0 (Etalab), réutilisables avec mention de la source
  (« Source : Météo-France »).
- DWD : données ouvertes du Deutscher Wetterdienst (ICON-EU), réutilisables
  avec mention de la source (« Source : Deutscher Wetterdienst »).
- ECMWF : données ouvertes du Centre européen pour les prévisions
  météorologiques à moyen terme, licence
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Les tuiles en
  sont une transformation (découpe et arrondi).

## Licence du code

MIT (voir [LICENSE](LICENSE)). Les données gardent la licence de leur source.
