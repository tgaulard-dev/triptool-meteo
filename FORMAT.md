# Format des tuiles météo TripTool (`.ttwx`, version 1)

Chaque cycle d'un modèle est découpé en tuiles fixes (5° × 5°, ou 1° × 1° pour
AROME, donné par `tileDegrees` dans le manifest). Une tuile
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

Coin sud-ouest, en degrés entiers multiples de `tileDegrees` : avec 5°,
`N45W005` couvre les latitudes [45, 50[ et les longitudes [-5, 0[ ; avec 1°,
`N48W005` couvre [48, 49[ et [-5, -4[. Latitude : `N`/`S` sur 2
chiffres ; longitude : `E`/`W` sur 3 chiffres. `S05` = [-5, 0[, `N00` = [0, 5[,
`W005` = [-5, 0[, `E000` = [0, 5[.

Les intervalles sont semi-ouverts : chaque point de grille appartient à une
seule tuile. Seule exception, la latitude 90 rejoint la rangée de tuiles la
plus au nord.
Les longitudes sont ramenées dans [-180, 180[.

## Contenu d'un fichier `.ttwx`

Le fichier entier (niveau 6) est compressé en DEFLATE brut (RFC 1951, sans en-tête zlib),
ce que lit directement `COMPRESSION_ZLIB` d'Apple. Une fois décompressé :

| Octets | Contenu |
|---|---|
| 4 | `TTWX` |
| 2 | version du format, entier non signé petit-boutiste (1) |
| 4 | longueur H de l'en-tête JSON, entier non signé petit-boutiste |
| H | en-tête JSON UTF-8 |
| reste | données (voir « Rangement des données ») |

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
- Valeur physique = `offset + brut × scale` ; `missing` = valeur absente.

## Rangement des données

Les valeurs brutes sont des entiers signés 16 bits, rangés par variable, puis
échéance, puis ligne, puis colonne (N = variables × échéances × nlat × nlon).
Deux transformations sans perte améliorent la compression :

1. **Écart à l'ouest** : sur chaque ligne, la première valeur est gardée telle
   quelle et chaque suivante est remplacée par sa différence avec la
   précédente, en arithmétique 16 bits modulaire (les valeurs `missing`
   y passent comme les autres).
2. **Plans d'octets** : les N octets de poids faible, puis les N octets de
   poids fort (2 × N octets au total).

Lecture : reconstituer chaque entier 16 bits non signé (faible | fort << 8),
faire la somme cumulée le long de chaque ligne modulo 65 536, puis
réinterpréter le résultat en entier signé.

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

## Paramètres (ICON-EU 0,0625°)

Mêmes noms que pour ECMWF, unités d'origine du DWD (différentes pour la pluie
et la nébulosité : l'unité figure dans l'en-tête de chaque tuile).

| Nom | Fichier DWD | Unité | scale | offset |
|---|---|---|---|---|
| `10u`, `10v` | `U_10M`, `V_10M` | m s-1 | 0,01 | 0 |
| `10fg` | `VMAX_10M` | m s-1 | 0,01 | 0 |
| `2t` | `T_2M` | K | 0,01 | 273,15 |
| `tp` | `TOT_PREC`, cumul depuis le début du run | kg m-2 (= mm) | 0,1 | 0 |
| `tcc` | `CLCT` | % | 0,01 | 0 |

ICON-EU couvre 23,5° O – 62,5° E et 29,5° N – 70,5° N : 180 tuiles, dont
celles du bord partiellement remplies.

## Paramètres (AROME 0,01°)

Paquets « 0,01° » horaires SP1 et SP2 de Météo-France, sauf la nébulosité
totale, absente de ces paquets : elle vient du paquet « 0,025° » SP1, reprise au
point 0,025° le plus proche. Domaine 37,5° N – 55,4° N, 12° O – 16° E.

| Nom | Origine | Unité | scale | offset |
|---|---|---|---|---|
| `10u`, `10v` | SP1 `U(10m)`, `V(10m)` | m s-1 | 0,01 | 0 |
| `10fg` | SP1 : norme de `U_RAF(10m)`, `V_RAF(10m)` (rafale max de l'heure) | m s-1 | 0,01 | 0 |
| `2t` | SP1 `T(2m)` | K | 0,01 | 273,15 |
| `tp` | SP2 : `EAU` + `NEIGE` + `GRAUPEL`, cumul depuis le début du run | kg m-2 (= mm) | 0,1 | 0 |
| `tcc` | 0,025° SP1 `NEBUL` | % | 0,01 | 0 |
| `cape` | SP2 `CAPE_INS` | J kg-1 | 1 | 0 |

À H+0, la rafale, la pluie et la nébulosité sont absentes (valeur `missing`).

## Paramètres (GFS 0,25°)

Archive ouverte de NOAA sur AWS (`noaa-gfs-bdp-pds`), mêmes fichiers que
NOMADS. Échéances de l'app : horaires jusqu'à H+120, puis toutes les 3 h
jusqu'à H+384 (209 échéances). Monde entier, tuiles de 5°.

| Nom | Champ GFS | Unité | scale | offset |
|---|---|---|---|---|
| `10u`, `10v` | `UGRD`, `VGRD` à 10 m | m s-1 | 0,01 | 0 |
| `10fg` | `GUST` en surface | m s-1 | 0,01 | 0 |
| `2t` | `TMP` à 2 m | K | 0,01 | 273,15 |
| `tp` | `APCP` « 0-N hour acc », cumul depuis le début du run | kg m-2 (= mm) | 0,1 | 0 |
| `tcc` | `TCDC` atmosphère entière, valeur instantanée | % | 0,01 | 0 |
| `cape` | `CAPE` en surface | J kg-1 | 1 | 0 |

À H+0, le cumul de pluie est absent (valeur `missing`).
