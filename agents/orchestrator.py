from __future__ import annotations
"""
TripOrchestrator — Coordina tutti gli agenti per generare un viaggio completo.

Flusso:
1. RouteAgent: calcola percorso con Mapbox, interpola punti tappa
2. CampsiteAgent: per ogni tappa, trova la sosta migliore (Claude + OSM)
3. POIAgent: per ogni sosta, cura i 3-4 highlights (Claude + OSM)
4. WeatherAgent: meteo per ogni sosta
5. NarratorAgent: racconto per ogni tappa + titolo/sommario viaggio
Tutto in parallelo dove possibile — ottimizzato per velocità.
"""
import asyncio
import uuid
from anthropic import AsyncAnthropic

from models.trip import TripRequest, TripResponse, Sosta
from tools.mapbox import get_route, interpolate_route_points, reverse_geocode
from tools.weather import get_weather_for_stop
from agents.poi_agent import curate_pois_for_stop
from agents.campsite_agent import find_best_campsite
from agents.narrator_agent import generate_tappa_narrative, generate_trip_summary
from config import get_settings

async def generate_trip(request: TripRequest) -> TripResponse:
    """Entry point principale: genera il viaggio completo."""
    settings = get_settings()
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    
    warnings = []
    
    # ── STEP 1: Routing ──────────────────────────────────────────────
    print(f"[Orchestrator] 🗺️ Calcolo percorso {request.partenza.nome} → {request.destinazione.nome}")
    route = await get_route(
        origin_lat=request.partenza.lat,
        origin_lng=request.partenza.lng,
        dest_lat=request.destinazione.lat,
        dest_lng=request.destinazione.lng,
        waypoints=[wp.model_dump() for wp in request.waypoints],
        mapbox_token=settings.mapbox_token,
    )
    
    if not route:
        warnings.append("Percorso Mapbox non disponibile — uso percorso lineare")
        route = _fallback_route(request)
    
    km_totali = route["distance_km"]
    print(f"[Orchestrator] ✅ Percorso: {km_totali:.0f} km, {route['duration_min']:.0f} min")
    
    # ── STEP 2: Interpola punti tappa sul percorso ────────────────────
    num_soste = request.num_giorni  # una sosta per notte (esclusa partenza)
    geometry = route.get("geometry", {})
    
    if geometry.get("coordinates"):
        punti_tappa = await interpolate_route_points(geometry, num_soste)
    else:
        punti_tappa = _linear_interpolate(request, num_soste)
    
    print(f"[Orchestrator] 📍 {len(punti_tappa)} punti tappa interpolati")
    
    # ── STEP 3: Campsite + POI + Meteo in parallelo per ogni tappa ───
    profilo = request.profilo.model_dump()
    
    # Calcola data per ogni tappa
    from datetime import datetime, timedelta
    data_base = None
    if request.data_partenza:
        try:
            data_base = datetime.strptime(request.data_partenza, "%Y-%m-%d")
        except:
            pass
    
    print(f"[Orchestrator] 🤖 Avvio agenti in parallelo per {len(punti_tappa)} tappe...")
    
    # Task paralleli per ogni tappa
    async def process_tappa(i: int, punto: dict) -> dict:
        giorno = i + 1
        target_lat = punto["lat"]
        target_lng = punto["lng"]
        target_km = punto["km"]
        
        # 3a: Campsite Agent
        campsite_task = find_best_campsite(
            target_lat=target_lat,
            target_lng=target_lng,
            target_km=target_km,
            giorno=giorno,
            profilo=profilo,
            anthropic_client=client,
            model=settings.claude_model,
        )
        
        # 3b: Weather Agent (non dipende da campsite)
        data_tappa = None
        if data_base:
            data_tappa = (data_base + timedelta(days=i)).strftime("%Y-%m-%d")
        
        weather_task = get_weather_for_stop(target_lat, target_lng, data_tappa)
        
        # Esegui campsite + meteo in parallelo
        campsite_result, meteo = await asyncio.gather(campsite_task, weather_task)
        
        # Usa coords campsite trovato (o fallback al punto interpolato)
        sosta_lat = campsite_result.get("lat", target_lat)
        sosta_lng = campsite_result.get("lng", target_lng)
        nome_sosta = campsite_result.get("nome", "")
        
        if not nome_sosta or campsite_result.get("fallback"):
            nome_sosta = await reverse_geocode(sosta_lat, sosta_lng, settings.mapbox_token)
        
        print(f"[Orchestrator] 🏕️ Giorno {giorno}: {nome_sosta} ({sosta_lat:.4f}, {sosta_lng:.4f})")
        
        # 3c: POI Agent — ora che sappiamo dove saremo
        poi_result = await curate_pois_for_stop(
            lat=sosta_lat,
            lng=sosta_lng,
            nome_sosta=nome_sosta,
            profilo=profilo,
            anthropic_client=client,
            model=settings.claude_model,
        )
        
        highlights = poi_result.get("highlights", [])
        zona_desc = poi_result.get("consiglio_zona", "")
        
        print(f"[Orchestrator] ⭐ Giorno {giorno}: {len(highlights)} highlights curati")
        
        # 3d: Narrator Agent
        km_giornata = target_km / giorno if giorno > 0 else km_totali / request.num_giorni
        racconto = await generate_tappa_narrative(
            giorno=giorno,
            nome_sosta=nome_sosta,
            km_giornata=km_giornata,
            highlights=highlights,
            meteo=meteo,
            profilo=profilo,
            zona_descrizione=zona_desc,
            anthropic_client=client,
            model=settings.claude_model,
        )
        
        return {
            "giorno": giorno,
            "nome": nome_sosta,
            "lat": sosta_lat,
            "lng": sosta_lng,
            "km_totali_percorsi": target_km,
            "tipo_sosta": campsite_result.get("tipo", "area_sosta"),
            "servizi": {s: True for s in campsite_result.get("servizi_presenti", [])},
            "ai_racconto": racconto,
            "highlights": highlights,
            "meteo": meteo,
            "motivo_sosta": campsite_result.get("motivo_scelta", ""),
        }
    
    # Processa TUTTE le tappe con concorrenza limitata (max 3 in parallelo per Overpass)
    sem = asyncio.Semaphore(3)
    async def process_with_sem(i, punto):
        async with sem:
            return await process_tappa(i, punto)
    
    tappe_results = await asyncio.gather(
        *[process_with_sem(i, p) for i, p in enumerate(punti_tappa)],
        return_exceptions=True
    )
    
    # Filtra eccezioni
    soste_dati = []
    for i, r in enumerate(tappe_results):
        if isinstance(r, Exception):
            warnings.append("Giorno " + str(i+1) + ": errore agente (" + str(r)[:50] + ")")
            soste_dati.append({
                "giorno": i+1, "nome": f"Tappa {i+1}",
                "lat": punti_tappa[i]["lat"], "lng": punti_tappa[i]["lng"],
                "km_totali_percorsi": punti_tappa[i]["km"],
                "ai_racconto": "", "highlights": [], "meteo": {},
            })
        else:
            soste_dati.append(r)
    
    # Aggiungi destinazione finale
    soste_dati.append({
        "giorno": request.num_giorni + 1,
        "nome": request.destinazione.nome,
        "lat": request.destinazione.lat,
        "lng": request.destinazione.lng,
        "km_totali_percorsi": km_totali,
        "tipo": "destinazione",
        "ai_racconto": "",
        "highlights": [],
        "meteo": await get_weather_for_stop(request.destinazione.lat, request.destinazione.lng),
    })
    
    # ── STEP 4: Titolo e sommario ─────────────────────────────────────
    print("[Orchestrator] ✍️ Generazione titolo e sommario...")
    titolo, sommario = await generate_trip_summary(
        partenza=request.partenza.nome,
        destinazione=request.destinazione.nome,
        num_giorni=request.num_giorni,
        km_totali=km_totali,
        soste=soste_dati,
        profilo=profilo,
        anthropic_client=client,
        model=settings.claude_model,
    )
    
    print(f"[Orchestrator] 🎉 Viaggio completato: '{titolo}'")
    
    # ── Build response ────────────────────────────────────────────────
    soste_model = []
    for s in soste_dati:
        km_da_prec = None
        if len(soste_model) > 0:
            prev = soste_model[-1]
            km_da_prec = round(s["km_totali_percorsi"] - prev.km_totali_percorsi, 1) if s.get("km_totali_percorsi") else None
        soste_model.append(Sosta(
            giorno=s["giorno"],
            nome=s["nome"],
            lat=s["lat"],
            lng=s["lng"],
            km_da_precedente=km_da_prec,
            km_totali_percorsi=s.get("km_totali_percorsi"),
            tipo=s.get("tipo", "overnight"),
            servizi=s.get("servizi", {}),
            ai_racconto=s.get("ai_racconto", ""),
            highlights=s.get("highlights", []),
            meteo=s.get("meteo") or None,
        ))
    
    return TripResponse(
        trip_id=str(uuid.uuid4()),
        titolo=titolo,
        sommario=sommario,
        num_giorni=request.num_giorni,
        km_totali=km_totali,
        soste=soste_model,
        route_geojson=geometry if geometry else None,
        status="ok",
        warnings=warnings,
    )

# ── Curate POIs for an existing trip stop (endpoint standalone) ──────
async def curate_stop_pois(
    lat: float, lng: float, nome: str, profilo: dict
) -> dict:
    settings = get_settings()
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return await curate_pois_for_stop(lat, lng, nome, profilo, client, settings.claude_model)

# ── Helpers ──────────────────────────────────────────────────────────
def _fallback_route(request: TripRequest) -> dict:
    from tools.osm import _haversine
    dist = _haversine(request.partenza.lat, request.partenza.lng,
                      request.destinazione.lat, request.destinazione.lng)
    return {
        "distance_km": dist * 1.3,  # fattore strada
        "duration_min": int(dist * 1.3 / 60 * 60),  # ~60 km/h media
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [request.partenza.lng, request.partenza.lat],
                [request.destinazione.lng, request.destinazione.lat],
            ]
        },
        "legs": []
    }

def _linear_interpolate(request: TripRequest, n: int) -> list[dict]:
    results = []
    for i in range(1, n + 1):
        t = i / (n + 1)
        results.append({
            "lat": request.partenza.lat + t * (request.destinazione.lat - request.partenza.lat),
            "lng": request.partenza.lng + t * (request.destinazione.lng - request.partenza.lng),
            "km": 0,
        })
    return results
