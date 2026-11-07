# triptool-meteo

Découpe les prévisions météo ouvertes en tuiles de 5° × 5° pour l'app iOS
[TripTool](https://triptool.app) : l'app ne télécharge que les tuiles de sa
zone (quelques centaines de Ko) au lieu des fichiers mondiaux ou européens
(plusieurs centaines de Mo par actualisation).

Format des tuiles : [FORMAT.md](FORMAT.md).

## Modèles

| Modèle | Source | Cycles | Statut |
|---|---|---|---|
| ECMWF IFS 0,25° | data.ecmwf.int (données ouvertes) | 00 et 12 UTC, jusqu'à H+240 | en place |
| ICON-EU | opendata.dwd.de | — | à venir |

## Fonctionnement

Le workflow [`.github/workflows/ecmwf.yml`](.github/workflows/ecmwf.yml)
vérifie chaque heure si un cycle plus récent que celui publié est complet.
Si oui : téléchargement des seuls champs utiles, découpe en 2 592 tuiles
(≈ 340 Mo pour le monde entier), envoi sur Cloudflare R2, puis mise à jour
de `ecmwf/latest.json` en dernier. Les deux derniers cycles sont conservés.

Secrets à définir dans le dépôt (Settings → Secrets and variables → Actions) :
`R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`.

## En local

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover tests
.venv/bin/python -m ttwx produce --out build --steps 0,3,48 --bbox 45,-10,50,0
.venv/bin/python tests/check_against_grib.py build/ecmwf/<cycle> <cycle> 48
```

`check_against_grib.py` compare les tuiles aux valeurs lues directement dans
le GRIB d'origine (coordonnées identiques, écart au plus l'arrondi du format).

## Sources et licences des données

- ECMWF : données ouvertes du Centre européen pour les prévisions
  météorologiques à moyen terme, licence
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Les tuiles en
  sont une transformation (découpe et arrondi).
