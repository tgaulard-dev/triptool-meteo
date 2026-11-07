# Format des tuiles météo TripTool (`.ttwx`, version 1)

Chaque cycle d'un modèle est découpé en tuiles fixes de 5° × 5°. Une tuile
contient toutes les échéances et tous les paramètres des points de grille
natifs qu'elle couvre : l'app ne télécharge que les tuiles de sa zone.

## Arborescence publiée

```
<modèle>/latest.json                  dernier cycle complet (écrit en dernier)
<modèle>/<AAAAMMJJHH>/manifest.json   description du cycle
<modèle>/<AAAAMMJJHH>/<tuile>.ttwx    une tuile
```

`latest.json` et `manifest.json` ont la même forme :

```json
{
  "format": 1,
  "model": "ecmwf",
  "run": "2026-11-07T00:00:00Z",
  "steps": [0, 3, 6, 240],
  "tileDegrees": 5,
  "variables": ["10u", "10v", "10fg", "2t", "tp", "tcc"],
  "tiles": 2592,
  "generated": "2026-11-07T08:12:40Z"
}
```

## Nom d'une tuile

Coin sud-ouest, en degrés entiers multiples de 5 : `N45W005` couvre les
latitudes [45, 50[ et les longitudes [-5, 0[. Latitude : `N`/`S` sur 2
chiffres ; longitude : `E`/`W` sur 3 chiffres. `S05` = [-5, 0[, `N00` = [0, 5[,
`W005` = [-5, 0[, `E000` = [0, 5[.

Les intervalles sont semi-ouverts : chaque point de grille appartient à une
seule tuile. Seule exception, la latitude 90 rejoint les tuiles `N85`.
Les longitudes sont ramenées dans [-180, 180[.

## Contenu d'un fichier `.ttwx`

Le fichier entier est compressé en DEFLATE brut (RFC 1951, sans en-tête zlib),
ce que lit directement `COMPRESSION_ZLIB` d'Apple. Une fois décompressé :

| Octets | Contenu |
|---|---|
| 4 | `TTWX` |
| 2 | version du format, entier non signé petit-boutiste (1) |
| 4 | longueur H de l'en-tête JSON, entier non signé petit-boutiste |
| H | en-tête JSON UTF-8 |
| reste | données, entiers signés 16 bits petit-boutistes |

En-tête :

```json
{
  "model": "ecmwf",
  "run": "2026-11-07T00:00:00Z",
  "steps": [0, 3, 6],
  "grid": {"lat0": 45.0, "lon0": -5.0, "dlat": 0.25, "dlon": 0.25, "nlat": 20, "nlon": 20},
  "variables": [
    {"name": "10u", "units": "m s-1", "scale": 0.01, "offset": 0.0}
  ],
  "missing": -32768
}
```

- `lat0`, `lon0` : point le plus au sud-ouest. Les lignes vont du sud au nord,
  les colonnes d'ouest en est : point (ligne r, colonne c) = (`lat0 + r·dlat`,
  `lon0 + c·dlon`).
- Données rangées par variable, puis échéance, puis ligne, puis colonne.
  Taille : variables × échéances × nlat × nlon × 2 octets.
- Valeur physique = `offset + brut × scale` ; `missing` = valeur absente.

## Paramètres (ECMWF IFS 0,25°)

Valeurs dans les unités GRIB d'origine : l'app les traite exactement comme
celles lues dans le GRIB.

| Nom | Sens | Unité | scale | offset |
|---|---|---|---|---|
| `10u`, `10v` | vent à 10 m, composantes est et nord | m s-1 | 0,01 | 0 |
| `10fg` | rafale max à 10 m | m s-1 | 0,01 | 0 |
| `2t` | température à 2 m | K | 0,01 | 273,15 |
| `tp` | précipitations cumulées depuis le début du run | m | 0,0001 | 0 |
| `tcc` | nébulosité totale | 0–1 | 0,0001 | 0 |

L'erreur de quantification (au plus scale / 2) reste inférieure à la
précision du codage GRIB d'origine.
