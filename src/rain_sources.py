"""Sources de pluie : Open-Meteo (modèle) et CHIRPS (satellite + stations).

Constat initial du projet : sur les 13-14 juin 2024, Open-Meteo donne 4 à 12 mm
alors que CHIRPS donne 66 à 107 mm autour d'Abidjan. Les deux sources ne sont
donc PAS interchangeables pour détecter les pluies extrêmes.
"""
from __future__ import annotations

import gzip
import io
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import tifffile

CACHE = Path(__file__).resolve().parent.parent / "data" / "cache"
CACHE.mkdir(parents=True, exist_ok=True)

OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
CHIRPS_URL = (
    "https://data.chc.ucsb.edu/products/CHIRPS-2.0/africa_daily/tifs/p05/"
    "{y}/chirps-v2.0.{y}.{m:02d}.{d:02d}.tif.gz"
)
# Grille CHIRPS Afrique : longitude -20..55 (1500 px), latitude 40..-40 (1600 px), pas 0,05 degré
LON0, LAT0, RES = -20.0, 40.0, 0.05
# Fenêtre mise en cache (Afrique de l'Ouest côtière) : lat 3..12, lon -12..2
Y0, X0 = int((LAT0 - 12) / RES), int((-12 - LON0) / RES)
Y1, X1 = int((LAT0 - 3) / RES), int((2 - LON0) / RES)


def openmeteo_daily(lat: float, lon: float, start: date, end: date, model: str = "best_match") -> pd.Series:
    """Pluie journalière (mm) du modèle Open-Meteo (archive). Gratuit, sans clé, usage non commercial."""
    r = requests.get(
        OPEN_METEO_ARCHIVE,
        params=dict(latitude=lat, longitude=lon, start_date=start.isoformat(),
                    end_date=end.isoformat(), daily="precipitation_sum",
                    timezone="Africa/Abidjan", models=model),
        timeout=60,
    )
    r.raise_for_status()
    d = r.json()["daily"]
    return pd.Series(d["precipitation_sum"], index=pd.to_datetime(d["time"]), name="openmeteo_mm", dtype="float")


OPEN_METEO_HIST_FORECAST = "https://historical-forecast-api.open-meteo.com/v1/forecast"
MODELES_PREVISION = ["ecmwf_ifs025", "gfs_seamless", "icon_seamless", "meteofrance_seamless", "ukmo_seamless"]


def openmeteo_previsions_passees(lat: float, lon: float, start: date, end: date,
                                 models: list[str] = MODELES_PREVISION) -> pd.DataFrame:
    """Ce que chaque modèle PRÉVOYAIT (courte échéance) pour chaque jour passé. Archive dispo. ~2022+.

    Sert à répondre à la question : « une alerte basée sur la prévision aurait-elle vu l'événement ? ».
    Constat 13-14 juin 2024 : 6 à 37 mm prévus contre 107 à 131 mm observés par CHIRPS.
    """
    r = requests.get(
        OPEN_METEO_HIST_FORECAST,
        params=dict(latitude=lat, longitude=lon, start_date=start.isoformat(), end_date=end.isoformat(),
                    daily="precipitation_sum", timezone="Africa/Abidjan", models=",".join(models)),
        timeout=60,
    )
    if r.status_code != 200:  # période hors archive
        return pd.DataFrame(index=pd.DatetimeIndex([], name="date"))
    d = r.json()["daily"]
    df = pd.DataFrame({m: d.get(f"precipitation_sum_{m}") for m in models},
                      index=pd.to_datetime(d["time"]), dtype="float")
    df.index.name = "date"
    df["prevision_max_mm"] = df[models].max(axis=1)
    df["prevision_med_mm"] = df[models].median(axis=1)
    return df[["prevision_max_mm", "prevision_med_mm"]]


def openmeteo_prevision_multimodele(lat: float, lon: float, days: int = 2,
                                    models: list[str] = MODELES_PREVISION) -> pd.Series:
    """Pluie journalière PRÉVUE (mm), maximum des modèles : même grandeur que celle calibrée en rejeu."""
    r = requests.get(
        OPEN_METEO_FORECAST,
        params=dict(latitude=lat, longitude=lon, daily="precipitation_sum", forecast_days=days,
                    timezone="Africa/Abidjan", models=",".join(models)),
        timeout=60,
    )
    r.raise_for_status()
    d = r.json()["daily"]
    df = pd.DataFrame({m: d.get(f"precipitation_sum_{m}") for m in models},
                      index=pd.to_datetime(d["time"]), dtype="float")
    return df.max(axis=1).rename("prevision_max_mm")


IMERG_EARLY_OPENDAP = (
    "https://gpm1.gesdisc.eosdis.nasa.gov/opendap/GPM_L3/GPM_3IMERGDE.07/{y}/{m:02d}/"
    "3B-DAY-E.MS.MRG.3IMERG.{y}{m:02d}{d:02d}-S000000-E235959.V07B.nc4.ascii?precipitation[0:0][{ilon}][{ilat}]"
)


def imerg_early_jour(day: date, lat: float, lon: float, token: str) -> float | None:
    """Pluie journalière IMERG Early (NASA, quelques heures de retard), en mm. None si indisponible.

    Nécessite un jeton NASA Earthdata (urs.earthdata.nasa.gov, gratuit) avec l'accès GES DISC autorisé.
    Grille 0,1° : longitude -179,95..179,95, latitude -89,95..89,95 (dimensions time, lon, lat en V07).
    EXPÉRIMENTAL : non calibré ; les seuils actuels ont été mesurés sur CHIRPS.
    """
    ilon = int(round((lon + 179.95) / 0.1))
    ilat = int(round((lat + 89.95) / 0.1))
    url = IMERG_EARLY_OPENDAP.format(y=day.year, m=day.month, d=day.day, ilon=ilon, ilat=ilat)
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    if r.status_code != 200:
        return None
    # réponse ASCII : un en-tête puis une ligne « [0][i], valeur »
    for ligne in r.text.splitlines():
        if ligne.startswith("[0]") and "," in ligne:
            try:
                v = float(ligne.rsplit(",", 1)[1])
            except ValueError:
                return None
            return None if v < 0 else v
    return None


def openmeteo_forecast_hourly(lat: float, lon: float, days: int = 3) -> pd.DataFrame:
    """Prévision horaire (mm et probabilité). Probablement sous-estime les pluies extrêmes : voir le rapport."""
    r = requests.get(
        OPEN_METEO_FORECAST,
        params=dict(latitude=lat, longitude=lon, hourly="precipitation,precipitation_probability",
                    forecast_days=days, timezone="Africa/Abidjan"),
        timeout=60,
    )
    r.raise_for_status()
    h = r.json()["hourly"]
    return pd.DataFrame(h).assign(time=lambda x: pd.to_datetime(x["time"])).set_index("time")


_ABSENTS: dict[date, float] = {}   # jour non publié -> heure du dernier essai (évite de redemander à chaque zone)
ABSENT_REESSAI_S = 6 * 3600


def _chirps_grid(day: date) -> np.ndarray | None:
    import time
    f = CACHE / f"chirps-{day.isoformat()}.npy"
    if f.exists():
        return np.load(f)
    if time.time() - _ABSENTS.get(day, 0) < ABSENT_REESSAI_S:
        return None
    url = CHIRPS_URL.format(y=day.year, m=day.month, d=day.day)
    r = requests.get(url, timeout=120)
    if r.status_code != 200:
        _ABSENTS[day] = time.time()
        return None
    grid = tifffile.imread(io.BytesIO(gzip.decompress(r.content))).astype("float32")
    grid[grid < -9000] = np.nan
    sub = grid[Y0:Y1, X0:X1].copy()
    np.save(f, sub)
    return sub


def chirps_point(day: date, lat: float, lon: float, radius_cells: int = 2) -> tuple[float, float] | None:
    """(maille centrale, maximum du carré ±radius_cells mailles) en mm/jour, ou None si le jour manque."""
    g = _chirps_grid(day)
    if g is None:
        return None
    y = int(round((LAT0 - lat) / RES)) - Y0
    x = int(round((lon - LON0) / RES)) - X0
    win = g[y - radius_cells:y + radius_cells + 1, x - radius_cells:x + radius_cells + 1]
    return float(g[y, x]), float(np.nanmax(win))


def chirps_series(lat: float, lon: float, start: date, end: date, workers: int = 8) -> pd.DataFrame:
    from concurrent.futures import ThreadPoolExecutor

    days = [start + timedelta(n) for n in range((end - start).days + 1)]
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(lambda d: chirps_point(d, lat, lon), days))
    rows = [(pd.Timestamp(d), r[0] if r else np.nan, r[1] if r else np.nan) for d, r in zip(days, res)]
    return pd.DataFrame(rows, columns=["date", "chirps_mm", "chirps_max_mm"]).set_index("date")


# --- Débits de rivière : GloFAS (Copernicus) via l'API Flood d'Open-Meteo, gratuite, sans clé ---
OPEN_METEO_FLOOD = "https://flood-api.open-meteo.com/v1/flood"


def glofas_debit(lat: float, lon: float, start: date | None = None, end: date | None = None,
                 forecast_days: int = 7) -> pd.Series:
    """Débit journalier (m³/s). Avec start/end : historique (réanalyse depuis 1984). Sinon : prévision."""
    import time
    params = dict(latitude=lat, longitude=lon, daily="river_discharge")
    cache = None
    if start:
        fin = end or date.today()
        params.update(start_date=start.isoformat(), end_date=fin.isoformat())
        if fin < date.today():      # historique figé : mis en cache sur disque
            cache = CACHE / f"glofas_{lat:.3f}_{lon:.3f}_{start}_{fin}.csv"
            if cache.exists():
                s = pd.read_csv(cache, parse_dates=["date"]).set_index("date")["debit_m3s"]
                return s.rename_axis(None)
    else:
        params.update(forecast_days=forecast_days)
    for essai in range(5):          # l'API gratuite refuse les rafales de grosses requêtes (429) : on patiente
        r = requests.get(OPEN_METEO_FLOOD, params=params, timeout=120)
        if r.status_code != 429:
            break
        time.sleep(20 * (essai + 1))
    r.raise_for_status()
    d = r.json()["daily"]
    serie = pd.Series(d["river_discharge"], index=pd.to_datetime(d["time"]), name="debit_m3s", dtype="float")
    if cache is not None:
        serie.rename_axis("date").to_csv(cache)
    return serie


def seuils_de_crue(historique: pd.Series) -> tuple[float, float]:
    """(seuil orange, seuil rouge) d'après les maxima annuels de débit.

    Orange = quantile 20 % des maxima annuels : la crue « annuelle », atteinte environ 4 années sur 5.
    Rouge = quantile 80 % : la crue « de 5 ans », rare et dommageable.
    Choix du 20 % (scripts/evaluer_crues.py, 9 crues documentées hors Abidjan) : 7/9 détectées pour ~1 épisode
    par an et par fleuve, contre 4/9 avec la crue de 2 ans (médiane). Échantillon petit : à revoir.
    """
    maxima = historique.dropna().groupby(historique.dropna().index.year).max()
    maxima = maxima[maxima.index < date.today().year]           # année en cours incomplète
    return float(maxima.quantile(0.2)), float(maxima.quantile(0.8))
