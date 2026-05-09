from __future__ import annotations
"""
Strumenti OSM/Overpass per gli agenti Claude.
Ogni funzione è pensata per essere chiamata come tool da Claude.
"""
import httpx
import asyncio
import random
from typing import Optional

OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

CATEGORY_QUERIES = {
    "campeggi": [
        "node[tourism=camp_site]",
        "way[tourism=camp_site]",
        "node[tourism=caravan_site]",
        "way[tourism=caravan_site]",
    ],
    "aree_sosta": [
        "node[tourism=caravan_site]",
        "way[tourism=caravan_site]",
        "node[amenity=parking][motorhome=yes]",
        "node[motorhome=yes]",
        "node[motorhome=designated]",
        "node[amenity=parking][motorhome=designated]",
    ],
    "attrazioni": [
        "node[tourism=attraction]",
        "way[tourism=attraction]",
        "node[historic=castle]",
        "way[historic=castle]",
        "node[tourism=museum]",
        "way[tourism=museum]",
        "node[historic=monument]",
    ],
    "natura": [
        "node[natural=peak]",
        "node[natural=waterfall]",
        "way[leisure=nature_reserve]",
        "relation[leisure=nature_reserve]",
        "way[boundary=national_park]",
        "node[natural=wood]",
        "way[natural=wood]",
    ],
    "panorami": [
        "node[tourism=viewpoint]",
        "way[tourism=viewpoint]",
    ],
    "ristoranti": [
        "node[amenity=restaurant]",
        "node[amenity=trattoria]",
        "node[amenity=osteria]",
        "node[amenity=agriturismo]",
    ],
    "spiagge": [
        "node[natural=beach]",
        "way[natural=beach]",
        "node[leisure=beach_resort]",
        "way[leisure=beach_resort]",
    ],
    "supermercati": [
        "node[shop=supermarket]",
        "way[shop=supermarket]",
        "node[shop=convenience]",
    ],
    "benzinai": [
        "node[amenity=fuel]",
    ],
    "acqua": [
        "node[amenity=water_point]",
        "node[amenity=drinking_water]",
        "node[amenity=water_point][motorhome=yes]",
    ],
    "scarico": [
        "node[amenity=sanitary_dump_station]",
        "node[motorhome=dump_station]",
    ],
    "borghi": [
        "node[place=village]",
        "node[place=hamlet]",
        "node[historic=town_gate]",
        "node[historic=city_gate]",
    ],
    "laghi": [
        "node[natural=water][water=lake]",
        "way[natural=water][water=lake]",
        "relation[natural=water][water=lake]",
    ],
}

EMOJI_MAP = {
    "campeggi": "⛺", "aree_sosta": "🚐", "attrazioni": "⭐",
    "natura": "🌿", "panorami": "👁️", "ristoranti": "🍽️",
    "spiagge": "🏖️", "supermercati": "🛒", "benzinai": "⛽",
    "acqua": "💧", "scarico": "♻️", "borghi": "🏘️", "laghi": "🏞️",
}

async def search_pois_overpass(
    lat: float, lng: float, 
    categoria: str, 
    radius_km: float = 15,
    limit: int = 20
) -> list[dict]:
    """Cerca POI via Overpass API per categoria e posizione."""
    radius_m = int(radius_km * 1000)
    lines = CATEGORY_QUERIES.get(categoria, ["node[tourism=attraction]"])
    query_lines = "\n".join(f"  {l}(around:{radius_m},{lat},{lng});" for l in lines)
    query = f"[out:json][timeout:10];\n(\n{query_lines}\n);\nout body center {limit};"
    
    for mirror in OVERPASS_MIRRORS:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(mirror, data={"data": query})
                resp.raise_for_status()
                data = resp.json()
                elements = data.get("elements", [])
                results = []
                for el in elements:
                    tags = el.get("tags", {})
                    name = (tags.get("name") or tags.get("name:it") or 
                            tags.get("operator") or tags.get("brand") or
                            _fallback_name(tags, categoria))
                    if not name:
                        continue
                    # Coordinate: node=dirette, way/relation=center
                    elat = el.get("lat") or el.get("center", {}).get("lat")
                    elng = el.get("lon") or el.get("center", {}).get("lon")
                    if not elat or not elng:
                        continue
                    results.append({
                        "id": str(el.get("id")),
                        "nome": name,
                        "lat": elat,
                        "lng": elng,
                        "categoria": categoria,
                        "emoji": EMOJI_MAP.get(categoria, "📍"),
                        "tags": {k: v for k, v in tags.items() 
                                 if k in ("name","tourism","amenity","historic","natural",
                                          "opening_hours","website","phone","fee","rating",
                                          "stars","rooms","motorhome","cuisine","description")},
                        "distanza_km": _haversine(lat, lng, elat, elng),
                    })
                results.sort(key=lambda x: x["distanza_km"])
                return results[:limit]
        except Exception as e:
            print(f"[OSM] mirror {mirror} failed: {e}")
            continue
    return []

async def search_campsites_near_point(
    lat: float, lng: float, radius_km: float = 20
) -> list[dict]:
    """Cerca campeggi e aree sosta in un raggio intorno a un punto."""
    camps = await search_pois_overpass(lat, lng, "campeggi", radius_km, 30)
    soste = await search_pois_overpass(lat, lng, "aree_sosta", radius_km, 30)
    combined = {p["id"]: p for p in camps + soste}
    results = list(combined.values())
    results.sort(key=lambda x: x["distanza_km"])
    return results

def _fallback_name(tags: dict, categoria: str) -> Optional[str]:
    if categoria in ("campeggi", "aree_sosta"):
        if tags.get("tourism") == "caravan_site": return "Area Sosta Camper"
        if tags.get("tourism") == "camp_site": return "Campeggio"
        if tags.get("motorhome") in ("yes","designated"): return "Area Sosta"
    return None

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import radians, cos, sin, asin, sqrt
    R = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return R * 2 * asin(sqrt(a))
