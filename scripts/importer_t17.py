"""Importe dans PostGIS la livraison cartographique v0 de M2 (T17).

La source est épinglée au commit de la branche carte-risques-v7. Elle comprend
des GeoJSON et deux formats compacts AQG2/AQB2 utilisés par la carte Leaflet.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import struct
import sys
import unicodedata
import urllib.error
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterator

import psycopg

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "dataset" / "t17_m2_v0"
COMMIT = "5f3f1720c7271750af6134b71a45018a40d59106"
BRANCH = "carte-risques-v7"
REPO = "Master-Mind-code/AquaSentinelle"
API_TREE = f"https://api.github.com/repos/{REPO}/git/trees/{COMMIT}?recursive=1"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/"

LAYER_INFO: dict[str, dict[str, Any]] = {
    "communes": {"libelle": "Limites des communes", "categorie": "coeur", "format": "GeoJSON", "type": "MultiPolygon"},
    "quartiers": {"libelle": "Repères de quartiers", "categorie": "coeur", "format": "GeoJSON", "type": "Point"},
    "sites_constates": {"libelle": "Sites constatés", "categorie": "coeur", "format": "GeoJSON", "type": "Point"},
    "cours_eau_noms": {"libelle": "Cours d’eau nommés OSM", "categorie": "coeur", "format": "GeoJSON", "type": "LineString"},
    "caniveaux": {"libelle": "Caniveaux de la maquette", "categorie": "second_plan", "format": "GeoJSON", "type": "LineString"},
    "bassins": {"libelle": "Bassins versants de la maquette", "categorie": "coeur", "format": "AQG2 compact", "type": "Polygon"},
    "carreaux_100m": {"libelle": "Grille de risque 100 m", "categorie": "coeur", "format": "AQG2 compact", "type": "Polygon", "resolution": 100},
    "carreaux_250m": {"libelle": "Grille de risque 250 m", "categorie": "coeur", "format": "AQG2 compact", "type": "Polygon", "resolution": 250},
    "cours_eau": {"libelle": "Cours d’eau modélisés", "categorie": "coeur", "format": "AQG2 compact", "type": "LineString"},
    "zones_debordement": {"libelle": "Zones de débordement", "categorie": "coeur", "format": "AQG2 compact", "type": "Polygon"},
    "analyse_terrain": {"libelle": "Classes de pente et de hauteur au-dessus du cours d’eau", "categorie": "coeur", "format": "AQG2 compact", "type": "Polygon"},
    "batiments_risque": {"libelle": "Empreintes de bâtiments et attributs de risque", "categorie": "coeur", "format": "AQB2 compact", "type": "Polygon"},
}

CAUSE_CARREAU = [
    "", "fond de talweg", "débordement d’une rivière", "pente moyenne",
    "bas-fond près d’un talweg", "zone de débordement d’un cours d’eau",
    "pente forte (glissement)", "zone basse, cuvette ou canal",
    "zone basse au bord de la lagune",
]
CAUSE_BATIMENT = [
    "pente forte (glissement)", "fond de talweg", "zone basse au bord de la lagune",
    "débordement d’une rivière", "pente moyenne", "bas-fond près d’un talweg",
    "zone basse, cuvette ou canal", "zone de débordement d’un cours d’eau", "",
]
COMMUNES_BATI: list[str] = []
SKIPPED_DEGENERATE: dict[str, int] = {}


def count_skipped(layer: str) -> None:
    SKIPPED_DEGENERATE[layer] = SKIPPED_DEGENERATE.get(layer, 0) + 1


def request_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "AquaSentinelle-T17/1.0"})
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read()


def source_paths() -> list[dict[str, Any]]:
    tree = json.loads(request_bytes(API_TREE))
    return [
        item for item in tree["tree"]
        if item.get("type") == "blob" and (
            item["path"].startswith("app/static/carte/couches/")
            or item["path"].startswith("app/static/carte/analyse/")
            or item["path"].startswith("app/static/carte/bati/")
            or item["path"] in {"app/static/carte/risque.html", "app/static/carte/LISEZMOI.md"}
        )
    ]


def prepare_sources() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    items = source_paths()

    def fetch(item: dict[str, Any]) -> dict[str, Any]:
        repo_path = item["path"]
        local_path = DATA / repo_path.removeprefix("app/static/carte/")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        content = request_bytes(RAW_BASE + repo_path)
        digest = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        if digest != item["sha"]:
            raise RuntimeError(f"Empreinte Git différente pour {repo_path}")
        local_path.write_bytes(content)
        return {
            "repository_path": repo_path,
            "local_path": local_path.relative_to(DATA).as_posix(),
            "git_blob_sha": digest,
            "bytes": len(content),
        }

    records: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch, item) for item in items]
        for number, future in enumerate(as_completed(futures), 1):
            records.append(future.result())
            if number % 50 == 0:
                print(f"Sources vérifiées et téléchargées : {number}/{len(items)}")
    manifest = {
        "repository": REPO,
        "branch": BRANCH,
        "commit": COMMIT,
        "snapshot_date": "2026-11-17",
        "files": sorted(records, key=lambda item: item["repository_path"]),
    }
    (DATA / "source_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Livraison récupérée : {len(records)} fichiers, {sum(x['bytes'] for x in records):,} octets.")


def load_manifest() -> dict[str, Any]:
    path = DATA / "source_manifest.json"
    if not path.exists():
        raise FileNotFoundError("Sources absentes. Exécuter d’abord --preparer.")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("commit") != COMMIT or manifest.get("branch") != BRANCH:
        raise RuntimeError("Le manifeste ne correspond pas à la version M2 épinglée.")
    missing = [row["local_path"] for row in manifest["files"] if not (DATA / row["local_path"]).exists()]
    if missing:
        raise FileNotFoundError("Fichiers manquants dans la livraison : " + ", ".join(missing[:8]))
    return manifest


def db_dsn() -> str:
    value = os.environ.get("DATABASE_URL")
    env_file = ROOT / ".env"
    if not value and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DATABASE_URL="):
                value = line.split("=", 1)[1].strip().strip("'\"")
                break
    if not value:
        value = "postgresql+psycopg://aqua:aqua@localhost:5434/aquasentinelle"
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def qcoord(value: float) -> str:
    return f"{value:.8f}"


def ring_wkt(points: list[tuple[float, float]]) -> str:
    points = [(float(point[0]), float(point[1])) for point in points]
    if len(set(points)) < 3:
        raise ValueError("Un anneau polygonal contient moins de trois sommets distincts.")
    if points[0] != points[-1]:
        points = [*points, points[0]]
    return "(" + ",".join(f"{qcoord(x)} {qcoord(y)}" for x, y in points) + ")"


def geometry_wkt(geometry: dict[str, Any]) -> str:
    kind = geometry["type"]
    coords = geometry["coordinates"]
    if kind == "Point":
        return "POINT(" + f"{qcoord(coords[0])} {qcoord(coords[1])}" + ")"
    if kind == "MultiPoint":
        return "MULTIPOINT(" + ",".join(f"({qcoord(p[0])} {qcoord(p[1])})" for p in coords) + ")"
    if kind == "LineString":
        return "LINESTRING(" + ",".join(f"{qcoord(p[0])} {qcoord(p[1])}" for p in coords) + ")"
    if kind == "MultiLineString":
        lines = ["(" + ",".join(f"{qcoord(p[0])} {qcoord(p[1])}" for p in line) + ")" for line in coords]
        return "MULTILINESTRING(" + ",".join(lines) + ")"
    if kind == "Polygon":
        rings = [ring_wkt(ring) for ring in coords]
        return "POLYGON(" + ",".join(rings) + ")"
    if kind == "MultiPolygon":
        polygons = ["(" + ",".join(ring_wkt(ring) for ring in polygon) + ")" for polygon in coords]
        return "MULTIPOLYGON(" + ",".join(polygons) + ")"
    raise ValueError(f"Type géométrique GeoJSON non pris en charge : {kind}")


def commune_slug(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")


def geojson_records(path: Path, layer: str) -> Iterator[tuple[str, str | None, dict[str, Any], str]]:
    obj = json.loads(path.read_text(encoding="utf-8-sig"))
    if obj.get("type") != "FeatureCollection":
        raise ValueError(f"{path.name}: GeoJSON n’est pas une FeatureCollection")
    for i, feature in enumerate(obj.get("features", [])):
        geometry = feature.get("geometry")
        if not geometry:
            count_skipped(layer)
            continue
        attrs = feature.get("properties") or {}
        commune = attrs.get("commune")
        if layer == "communes":
            commune = attrs.get("nom")
        source_id = f"{path.relative_to(DATA).as_posix()}#{i}"
        try:
            wkt = geometry_wkt(geometry)
        except ValueError:
            count_skipped(layer)
            continue
        yield source_id, commune, attrs, wkt


def read_u(raw: bytes, position: list[int]) -> int:
    value = 0
    shift = 0
    while True:
        if position[0] >= len(raw):
            raise ValueError("AQG2 : entier variable tronqué")
        byte = raw[position[0]]
        position[0] += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value
        shift += 7
        if shift > 63:
            raise ValueError("AQG2 : entier variable trop long")


def aqg2_records(path: Path, layer: str) -> Iterator[tuple[str, str | None, dict[str, Any], str]]:
    encoded = base64.b64decode(path.read_bytes().strip(), validate=True)
    raw = zlib.decompress(encoded)
    if raw[:4] != b"AQG2":
        raise ValueError(f"{path.name}: signature AQG2 absente")
    meta_length = struct.unpack_from("<I", raw, 4)[0]
    meta = json.loads(raw[8:8 + meta_length].decode("utf-8"))
    pos = [8 + meta_length]
    x = y = 0
    origin_x, origin_y = meta["o"]
    resolution = meta["r"]
    polygon = meta["genre"] == "polygone"

    def ring() -> list[tuple[float, float]]:
        nonlocal x, y
        points = []
        count = read_u(raw, pos)
        for _ in range(count):
            dx, dy = read_u(raw, pos), read_u(raw, pos)
            dx = -(dx + 1) // 2 if dx & 1 else dx // 2
            dy = -(dy + 1) // 2 if dy & 1 else dy // 2
            x += dx
            y += dy
            points.append((origin_x + x * resolution, origin_y + y * resolution))
        return points

    for feature_number in range(meta["n"]):
        values = [read_u(raw, pos) for _ in meta.get("props", [])]
        part_count = read_u(raw, pos)
        parts: list[Any] = []
        for _ in range(part_count):
            if polygon:
                ring_count = read_u(raw, pos)
                parts.append([ring() for _ in range(ring_count)])
            else:
                parts.append(ring())
        attrs = aqg2_attributes(layer, meta, values)
        if polygon:
            polygons = []
            for rings in parts:
                if not rings:
                    continue
                try:
                    outer = ring_wkt(rings[0])
                except ValueError:
                    count_skipped(layer)
                    continue
                holes = []
                for hole in rings[1:]:
                    try:
                        holes.append(ring_wkt(hole))
                    except ValueError:
                        count_skipped(layer)
                polygons.append("(" + ",".join([outer, *holes]) + ")")
            if not polygons:
                count_skipped(layer)
                continue
            wkt = "MULTIPOLYGON(" + ",".join(polygons) + ")"
        else:
            lines = ["(" + ",".join(f"{qcoord(a)} {qcoord(b)}" for a, b in points) + ")" for points in parts if len(set(points)) >= 2]
            if not lines:
                count_skipped(layer)
                continue
            wkt = "MULTILINESTRING(" + ",".join(lines) + ")"
        yield f"{path.relative_to(DATA).as_posix()}#{feature_number}", None, attrs, wkt


def aqg2_attributes(layer: str, meta: dict[str, Any], values: list[int]) -> dict[str, Any]:
    raw_values = dict(zip(meta.get("props", []), values))
    if layer in {"carreaux_100m", "carreaux_250m"}:
        cause_code = raw_values.get("c", 0)
        return {
            "batiments": raw_values.get("b"),
            "pct_batiments_a_risque": raw_values.get("r"),
            "population_2026_estimee": raw_values.get("p"),
            "population_2026_estimee_a_risque": raw_values.get("pr"),
            "cause_code": cause_code,
            "cause_principale": CAUSE_CARREAU[cause_code] if cause_code < len(CAUSE_CARREAU) else None,
            "resolution_m": 100 if layer == "carreaux_100m" else 250,
            "valeurs_source": raw_values,
        }
    if layer == "cours_eau":
        value = raw_values.get("bassin_x10")
        return {"bassin_amont_km2": value / 10 if value is not None else None, "bassin_x10_source": value}
    if layer == "analyse_terrain":
        raw_layer = raw_values.get("couche")
        return {
            "facteur": {0: "pente", 1: "hand"}.get(raw_layer, f"code_{raw_layer}"),
            "classe_code": raw_values.get("classe"),
            "valeurs_source": raw_values,
        }
    return raw_values


def batiment_records(path: Path, communes: list[str]) -> Iterator[tuple[str, str | None, dict[str, Any], str]]:
    raw = zlib.decompress(base64.b64decode(path.read_bytes().strip(), validate=True))
    if raw[:4] != b"AQB2":
        raise ValueError(f"{path.name}: signature AQB2 absente")
    count = struct.unpack_from("<I", raw, 4)[0]
    origin_x, origin_y = struct.unpack_from("<dd", raw, 8)
    pos = 24
    vertex_counts = raw[pos:pos + count]; pos += count
    risk_codes = raw[pos:pos + count]; pos += count
    flags = raw[pos:pos + count]; pos += count
    commune_codes = raw[pos:pos + count]; pos += count
    attributes_offset = pos
    pos += 14 * count
    x = y = first_x = first_y = 0

    def varint() -> int:
        nonlocal pos
        value = 0
        shift = 0
        while True:
            if pos >= len(raw):
                raise ValueError("AQB2 : coordonnée tronquée")
            byte = raw[pos]
            pos += 1
            value |= (byte & 127) << shift
            if byte < 128:
                return value
            shift += 7
            if shift > 63:
                raise ValueError("AQB2 : coordonnée invalide")

    for i, vertex_count in enumerate(vertex_counts):
        points: list[tuple[float, float]] = []
        for j in range(vertex_count):
            dx, dy = varint(), varint()
            dx = -(dx + 1) // 2 if dx & 1 else dx // 2
            dy = -(dy + 1) // 2 if dy & 1 else dy // 2
            if j == 0:
                x, y = first_x + dx, first_y + dy
                first_x, first_y = x, y
            else:
                x += dx
                y += dy
            points.append((origin_x + x * 1e-6, origin_y + y * 1e-6))
        if len(points) < 3:
            count_skipped("batiments_risque")
            continue
        if points[0] != points[-1]:
            points.append(points[0])
        code = int(risk_codes[i])
        flag = int(flags[i])
        commune_code = int(commune_codes[i])
        commune = communes[commune_code] if commune_code < len(communes) else None
        att = struct.unpack_from("<7H", raw, attributes_offset + 14 * i)
        def scaled(value: int, divisor: float, offset: float = 0) -> float | None:
            return None if value == 65535 else (value - offset) / divisor
        risk_level = "très élevé" if code <= 3 else "élevé" if code <= 7 else "faible"
        attrs = {
            "code_risque_source": code,
            "niveau_risque": risk_level,
            "cause_code": code,
            "cause": CAUSE_BATIMENT[code] if code < len(CAUSE_BATIMENT) and CAUSE_BATIMENT[code] else None,
            "commune_code_source": commune_code,
            "indicateurs": {
                "population_estimee": scaled(att[0], 10),
                "pente_degres": scaled(att[1], 10),
                "hauteur_au_dessus_cours_eau_m": scaled(att[2], 10),
                "bassin_amont_km2": scaled(att[3], 100),
                "hauteur_batiment_2023_m": scaled(att[4], 10),
                "altitude_m": scaled(att[5], 10, 1000),
                "attribut_7_brut_non_documente": None if att[6] == 65535 else att[6],
            },
            "dans_zone_debordement": bool(flag & 1),
            "construit_apres_2016": ("oui" if flag & 2 else "non") if flag & 4 else "non mesuré",
            "flags_source": flag,
            "attributs_u16_source": list(att),
        }
        try:
            wkt = "POLYGON(" + ring_wkt(points) + ")"
        except ValueError:
            count_skipped("batiments_risque")
            continue
        yield (
            f"{path.relative_to(DATA).as_posix()}#{i}",
            commune,
            attrs,
            wkt,
        )


def layer_and_records(path: Path, bidx_communes: list[str]) -> tuple[str, Iterator[tuple[str, str | None, dict[str, Any], str]]]:
    rel = path.relative_to(DATA).as_posix()
    if rel.startswith("bati/") and path.suffix == ".txt":
        return "batiments_risque", batiment_records(path, bidx_communes)
    if rel.startswith("analyse/") and path.suffix == ".txt":
        return "analyse_terrain", aqg2_records(path, "analyse_terrain")
    names = {
        "bassins.txt": "bassins",
        "carreaux_100m.txt": "carreaux_100m",
        "carreaux_250m.txt": "carreaux_250m",
        "cours_eau.txt": "cours_eau",
        "zones_debordement.txt": "zones_debordement",
        "caniveaux.geojson": "caniveaux",
        "communes.geojson": "communes",
        "cours_eau_noms_osm.geojson": "cours_eau_noms",
        "quartiers.geojson": "quartiers",
        "sites_constates.geojson": "sites_constates",
    }
    layer = names.get(path.name)
    if not layer:
        raise ValueError(f"Fichier de couche inconnu : {rel}")
    records = geojson_records(path, layer) if path.suffix == ".geojson" else aqg2_records(path, layer)
    return layer, records


def record_files() -> list[Path]:
    manifest = load_manifest()
    files = []
    for row in manifest["files"]:
        rel = row["local_path"]
        if rel.startswith("couches/") and (rel.endswith(".geojson") or Path(rel).name in {
            "bassins.txt", "carreaux_100m.txt", "carreaux_250m.txt", "cours_eau.txt", "zones_debordement.txt"
        }):
            files.append(DATA / rel)
        elif rel.startswith("analyse/") and rel.endswith(".txt"):
            files.append(DATA / rel)
        elif rel.startswith("bati/") and rel.endswith(".txt"):
            files.append(DATA / rel)
    return sorted(files)


def metadata_for(layer: str, files: list[Path]) -> dict[str, Any]:
    info = dict(LAYER_INFO[layer])
    info["commit"] = COMMIT
    info["paths"] = [p.relative_to(DATA).as_posix() for p in files]
    dictionaries = {
        "carreaux_100m": {"b": "nombre de bâtiments", "r": "% de bâtiments classés à risque", "p": "population 2026 estimée", "pr": "population 2026 estimée à risque", "c": "index dans causes AQG2"},
        "carreaux_250m": {"b": "nombre de bâtiments", "r": "% de bâtiments classés à risque", "p": "population 2026 estimée", "pr": "population 2026 estimée à risque", "c": "index dans causes AQG2"},
        "cours_eau": {"bassin_x10": "surface du bassin amont en dixièmes de km²"},
        "zones_debordement": {"niveau": "classe source 1 ou 2"},
        "analyse_terrain": {"couche": "0=pente, 1=HAND", "classe": "classe source 0 à 2"},
        "batiments_risque": {"code": "code combinant niveau et cause selon la maquette", "flags": "bit 1=zone débordement; bits 2/4=construction après 2016 mesurée", "att0-att5": "population, pente, HAND, bassin amont, hauteur bâtiment, altitude (échelles documentées dans risque.html)", "att6": "valeur conservée brute, sens non exposé dans la maquette"},
        "caniveaux": {"id_troncon": "identifiant du tronçon", "longueur_m": "mètres", "surface_apport_ha": "hectares", "debit_envoye_m3s": "m³/s, estimation de la maquette"},
    }
    info["dictionary"] = dictionaries.get(layer, {"properties": "propriétés conservées telles que livrées par M2"})
    return info


def expected_layer_count(layer: str, files: list[Path], building_index: dict[str, int]) -> int:
    skipped_before = dict(SKIPPED_DEGENERATE)
    total = 0
    for path in files:
        if layer == "batiments_risque":
            total += building_index[path.name]
        elif path.suffix == ".geojson":
            obj = json.loads(path.read_text(encoding="utf-8-sig"))
            for feature in obj.get("features", []):
                try:
                    geometry_wkt(feature["geometry"])
                except (KeyError, TypeError, ValueError):
                    continue
                total += 1
        else:
            total += sum(1 for _ in aqg2_records(path, layer))
    SKIPPED_DEGENERATE.clear()
    SKIPPED_DEGENERATE.update(skipped_before)
    return total


def apply_schema(conn: psycopg.Connection) -> None:
    schema = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
    conn.execute(schema)
    conn.commit()


def import_data(resume: bool = False) -> None:
    load_manifest()
    index = json.loads((DATA / "bati" / "index.json").read_text(encoding="utf-8"))
    bidx_communes = index["communes"]
    files = record_files()
    grouped: dict[str, list[Path]] = {}
    for path in files:
        layer, _ = layer_and_records(path, bidx_communes)
        grouped.setdefault(layer, []).append(path)
    building_index = {part["f"]: int(part["n"]) for part in index["morceaux"]}

    with psycopg.connect(db_dsn()) as conn:
        apply_schema(conn)
        if not resume:
            with conn.transaction():
                conn.execute("DELETE FROM t17_entite")
                conn.execute("DELETE FROM t17_couche")
        conn.execute("""
            CREATE TEMP TABLE IF NOT EXISTS t17_stage (
              source_id text, commune text, attributs text, geom_wkt text
            ) ON COMMIT PRESERVE ROWS
        """)
        conn.commit()
        for layer, layer_files in sorted(grouped.items()):
            info = metadata_for(layer, layer_files)
            expected_count = expected_layer_count(layer, layer_files, building_index)
            previous = conn.execute("SELECT nb_entites FROM t17_couche WHERE id=%s", (layer,)).fetchone()
            if resume and previous and previous[0] == expected_count:
                print(f"{layer}: déjà complet ({expected_count:,} entités), conservé.", flush=True)
                continue
            if resume and previous:
                with conn.transaction():
                    conn.execute("DELETE FROM t17_entite WHERE couche_id=%s", (layer,))
                    conn.execute("UPDATE t17_couche SET nb_entites=0 WHERE id=%s", (layer,))
            conn.execute("""
                INSERT INTO t17_couche
                  (id,libelle,categorie,format_source,type_geometrie,resolution_m,source_commit,chemins_source,dictionnaire)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)
                ON CONFLICT (id) DO UPDATE SET
                  libelle=EXCLUDED.libelle, categorie=EXCLUDED.categorie,
                  format_source=EXCLUDED.format_source, type_geometrie=EXCLUDED.type_geometrie,
                  resolution_m=EXCLUDED.resolution_m, source_commit=EXCLUDED.source_commit,
                  chemins_source=EXCLUDED.chemins_source, dictionnaire=EXCLUDED.dictionnaire
            """, (
                layer, info["libelle"], info["categorie"], info["format"], info["type"],
                info.get("resolution"), COMMIT,
                json.dumps(info["paths"], ensure_ascii=False),
                json.dumps(info["dictionary"], ensure_ascii=False),
            ))
            conn.commit()
            total = 0
            for path in layer_files:
                _, records = layer_and_records(path, bidx_communes)
                count = 0
                with conn.transaction():
                    conn.execute("TRUNCATE t17_stage")
                    if layer == "communes":
                        _, zone_records = layer_and_records(path, bidx_communes)
                        for _, commune, _, wkt in zone_records:
                            sync_zone(conn, commune or "", wkt)
                    with conn.cursor().copy(
                        "COPY t17_stage (source_id,commune,attributs,geom_wkt) FROM STDIN"
                    ) as copy:
                        for source_id, commune, attrs, wkt in records:
                            copy.write_row((source_id, commune, json.dumps(attrs, ensure_ascii=False, allow_nan=False), wkt))
                            count += 1
                    conn.execute("""
                        INSERT INTO t17_entite (couche_id,source_id,commune,attributs,geom,source_commit)
                        SELECT %s,source_id,commune,attributs::jsonb,
                               CASE WHEN ST_IsValid(geom) THEN geom ELSE ST_MakeValid(geom) END,%s
                        FROM (
                          SELECT source_id,commune,attributs,
                                 ST_SetSRID(ST_GeomFromText(geom_wkt),4326) AS geom
                          FROM t17_stage
                        ) parsed
                    """, (layer, COMMIT))
                    conn.execute("UPDATE t17_couche SET nb_entites=nb_entites+%s, importee_le=now() WHERE id=%s", (count, layer))
                total += count
                print(f"{layer}: {path.name} — {count:,} entités (total {total:,})", flush=True)
            if total != expected_count:
                raise RuntimeError(f"{layer}: {total} entités importées, {expected_count} attendues dans la livraison.")
        conn.execute("ANALYZE t17_entite")
        conn.commit()
    print("Import T17 terminé.")
    print("Anneaux/entités géométriques dégénérés écartés pendant cette exécution :", SKIPPED_DEGENERATE or "aucun")


def sync_zone(conn: psycopg.Connection, commune: str, wkt: str) -> None:
    zone_id = commune_slug(commune)
    conn.execute("""
      INSERT INTO zone (id,nom,contour,centre,langue,region,type)
      VALUES (%s,%s,ST_Multi(ST_SetSRID(ST_GeomFromText(%s),4326)),
              ST_PointOnSurface(ST_SetSRID(ST_GeomFromText(%s),4326)), 'fr','District d’Abidjan','urbaine')
      ON CONFLICT (id) DO UPDATE SET
        nom=EXCLUDED.nom, contour=EXCLUDED.contour, centre=EXCLUDED.centre,
        region=EXCLUDED.region, type=EXCLUDED.type
    """, (zone_id, commune, wkt, wkt))


def verify_import() -> None:
    with psycopg.connect(db_dsn()) as conn:
        rows = conn.execute("SELECT id,nb_entites FROM t17_couche ORDER BY id").fetchall()
        print("Entités importées par couche :")
        for layer, count in rows:
            print(f"  {layer}: {count:,}")
        communes = conn.execute("""
          SELECT id,ST_IsValid(contour) AS valide FROM zone
          WHERE id IN ('abobo','adjame','anyama','attecoube','bingerville','cocody','koumassi',
                       'marcory','plateau','port-bouet','songon','treichville','yopougon')
          ORDER BY id
        """).fetchall()
        if len(communes) != 13 or not all(valid for _, valid in communes):
            raise RuntimeError(f"Limites de communes absentes ou invalides : {communes}")
        spatial = conn.execute("""
          SELECT z.id,count(e.id)
          FROM zone z
          LEFT JOIN t17_entite e ON e.couche_id='batiments_risque' AND ST_Intersects(e.geom,z.contour)
          WHERE z.id = ANY(%s)
          GROUP BY z.id ORDER BY z.id
        """, ([id_ for id_, _ in communes],)).fetchall()
        empty = [id_ for id_, count in spatial if count == 0]
        for id_, count in spatial:
            print(f"  ST_Intersects bâtiments {id_}: {count:,}")
        if empty:
            raise RuntimeError("Aucun bâtiment ne croise les communes : " + ", ".join(empty))
        invalid = conn.execute("""
          SELECT couche_id,count(*) FROM t17_entite WHERE NOT ST_IsValid(geom)
          GROUP BY couche_id ORDER BY couche_id
        """).fetchall()
        print("Géométries invalides par couche :", invalid or "aucune")
        overlaps = conn.execute("""
          SELECT a.nom,b.nom,round(ST_Area(ST_Intersection(a.contour,b.contour)::geography)::numeric,1)
          FROM zone a JOIN zone b
            ON a.id<b.id AND a.contour && b.contour
           AND ST_Area(ST_Intersection(a.contour,b.contour)::geography)>1
          WHERE a.id = ANY(%s) AND b.id = ANY(%s)
          ORDER BY 3 DESC
        """, ([id_ for id_, _ in communes], [id_ for id_, _ in communes])).fetchall()
        print("Recouvrements de limites à valider avec M2 :", overlaps or "aucun détecté")
    print("Requête spatiale T17 réussie.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--preparer", action="store_true", help="télécharger la livraison M2 épinglée et vérifier les empreintes")
    group.add_argument("--importer", action="store_true", help="créer le schéma T17 et charger les couches dans PostGIS")
    group.add_argument("--reprendre", action="store_true", help="reprendre l’import sans recharger les couches déjà complètes")
    group.add_argument("--verifier", action="store_true", help="vérifier les communes et les croisements spatiaux")
    args = parser.parse_args()
    if args.preparer:
        prepare_sources()
    elif args.importer:
        import_data()
    elif args.reprendre:
        import_data(resume=True)
    else:
        verify_import()


if __name__ == "__main__":
    try:
        main()
    except (OSError, urllib.error.URLError, psycopg.Error, ValueError, RuntimeError) as exc:
        print(f"Erreur T17 : {exc}", file=sys.stderr)
        raise SystemExit(1)
