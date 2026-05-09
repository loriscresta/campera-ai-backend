"""
Strumenti Mapbox per routing e geocoding.
"""
import httpx
from typing import Optional

async def get_route(
    origin_lat: float, origin_lng: float,
    dest_lat: float, dest_lng: float,
    waypoints: list[dict] = [],
    mapbox_token: str = ""
) -> Optional[dict]:
    """Calcola il percorso ottimale per camper via Mapbox Directions API."""
    coords = [f"{origin_lng},{origin_lat}"]
    for wp in waypoints:
        coords.append(f"{wp['lng']},{wp['lat']}")
    coords.append(f"{dest_lng},{dest_lat}")
    
    coords_str = ";".join(coords)
    url = f"https://api.mapbox.com/directions/v5/mapbox/driving/{coords_str}"
    
    params = {
        "access_token": mapbox_token,
        "geometries": "geojson",
        "overview": "full",
        "steps": "false",
        "annotations": "distance,duration",
    }
    
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            routes = data.get("routes", [])
            if not routes:
                return None
            route = routes[0]
            return {
                "distance_km": round(route["distance"] / 1000, 1),
                "duration_min": round(route["duration"] / 60),
                "geometry": route["geometry"],
                "legs": [
                    {"distance_km": round(leg["distance"]/1000, 1),
                     "duration_min": round(leg["duration"]/60)}
                    for leg in route.get("legs", [])
                ]
            }
    except Exception as e:
        print(f"[Mapbox] routing error: {e}")
        return None

async def interpolate_route_points(
    geometry: dict, 
    num_points: int
) -> list[dict]:
    """Interpola N punti equidistanti lungo la geometria del percorso."""
    coords = geometry.get("coordinates", [])
    if not coords or num_points < 1:
        return []
    
    from math import radians, cos, sin, asin, sqrt
    
    def haversine(a, b):
        R = 6371
        dlat = radians(b[1] - a[1])
        dlon = radians(b[0] - a[0])
        h = sin(dlat/2)**2 + cos(radians(a[1]))*cos(radians(b[1]))*sin(dlon/2)**2
        return R * 2 * asin(sqrt(max(0, h)))
    
    # Calcola distanze cumulative
    cum = [0.0]
    for i in range(1, len(coords)):
        cum.append(cum[-1] + haversine(coords[i-1], coords[i]))
    
    total = cum[-1]
    points = []
    for i in range(1, num_points + 1):
        target_km = (i / (num_points + 1)) * total
        # Trova il segmento
        for j in range(1, len(cum)):
            if cum[j] >= target_km:
                t = (target_km - cum[j-1]) / max(0.001, cum[j] - cum[j-1])
                lng = coords[j-1][0] + t * (coords[j][0] - coords[j-1][0])
                lat = coords[j-1][1] + t * (coords[j][1] - coords[j-1][1])
                points.append({"lat": lat, "lng": lng, "km": round(target_km, 1)})
                break
    
    return points

async def reverse_geocode(lat: float, lng: float, mapbox_token: str) -> str:
    """Geocoding inverso: coords → nome luogo."""
    url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{lng},{lat}.json"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params={
                "access_token": mapbox_token,
                "types": "place,locality,region",
                "language": "it",
                "limit": 1,
            })
            data = resp.json()
            features = data.get("features", [])
            if features:
                return features[0].get("place_name", f"{lat:.4f},{lng:.4f}")
    except:
        pass
    return f"{lat:.4f},{lng:.4f}"
