from __future__ import annotations
"""
Campera AI Backend — FastAPI
Agenti Claude per pianificazione viaggi camper intelligente.

Endpoints:
  POST /api/generate-trip      → viaggio completo con AI
  POST /api/curate-pois        → highlights curati per una sosta
  GET  /api/health             → healthcheck
  GET  /api/docs               → Swagger UI (auto)
"""
import asyncio
import json
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List

from config import get_settings
from models.trip import TripRequest, TripResponse
from agents.orchestrator import generate_trip, curate_stop_pois

settings = get_settings()

app = FastAPI(
    title="Campera AI Backend",
    description="Agenti Claude per viaggi in camper intelligenti",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Healthcheck ────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "model": settings.claude_model,
        "mapbox": bool(settings.mapbox_token),
        "anthropic": bool(settings.anthropic_api_key),
    }
# ── Debug (temporaneo) ─────────────────────────────────────────────
@app.get("/api/debug")
async def debug_env():
    import os
    raw_key = os.getenv("ANTHROPIC_API_KEY", "")
    return {
        "raw_key_len": len(raw_key),
        "raw_key_preview": (raw_key[:6] + "..." + raw_key[-4:]) if len(raw_key) > 10 else f"EMPTY({len(raw_key)})",
        "raw_key_starts_sk": raw_key.startswith("sk-"),
        "settings_key_len": len(settings.anthropic_api_key),
        "all_env_keys": sorted(os.environ.keys()),
    }
# ── Generate Trip ──────────────────────────────────────────────────
@app.post("/api/generate-trip", response_model=TripResponse)
async def api_generate_trip(request: TripRequest):
    """
    Genera un viaggio completo in camper con AI.
    
    Usa Claude multi-agent per:
    - Calcolare il percorso ottimale
    - Trovare le soste migliori (non solo le più vicine)
    - Curare i POI highlights per ogni tappa
    - Generare meteo e racconti coinvolgenti
    """
    if not settings.anthropic_api_key:
        raise HTTPException(500, "ANTHROPIC_API_KEY non configurata")
    if not settings.mapbox_token:
        raise HTTPException(500, "MAPBOX_TOKEN non configurato")
    
    try:
        result = await generate_trip(request)
        return result
    except Exception as e:
        raise HTTPException(500, f"Errore generazione viaggio: {str(e)}")

# ── Curate POIs for existing stop ─────────────────────────────────
class CuratePOIsRequest(BaseModel):
    lat: float
    lng: float
    nome: str = ""
    stili: List[str] = ["natura"]
    con_bambini: bool = False
    con_animali: bool = False
    budget: str = "medio"

@app.post("/api/curate-pois")
async def api_curate_pois(request: CuratePOIsRequest):
    """
    Cura i POI più interessanti per una sosta esistente.
    Endpoint standalone usato dal frontend Base44 per arricchire
    le tappe al momento del caricamento del viaggio.
    """
    if not settings.anthropic_api_key:
        raise HTTPException(500, "ANTHROPIC_API_KEY non configurata")
    
    profilo = {
        "stili": request.stili,
        "con_bambini": request.con_bambini,
        "con_animali": request.con_animali,
        "budget": request.budget,
    }
    
    try:
        result = await curate_stop_pois(request.lat, request.lng, request.nome, profilo)
        return result
    except Exception as e:
        raise HTTPException(500, f"Errore curazione POI: {str(e)}")

# ── Streaming endpoint — per feedback real-time al frontend ───────
@app.post("/api/generate-trip-stream")
async def api_generate_trip_stream(request: TripRequest):
    """
    Come /generate-trip ma con Server-Sent Events per mostrare
    il progresso in tempo reale: "Sto cercando soste per il giorno 2..."
    """
    if not settings.anthropic_api_key:
        raise HTTPException(500, "ANTHROPIC_API_KEY non configurata")
    
    async def event_generator():
        # Patch per intercettare i print dell'orchestrator e streamarli
        import sys
        from io import StringIO
        
        # Simple approach: genera e streama il risultato finale
        # TODO: implementare streaming granulare con asyncio.Queue
        try:
            yield f"data: {json.dumps({'type':'start','message':'Avvio pianificazione...'})}\n\n"
            result = await generate_trip(request)
            yield f"data: {json.dumps({'type':'result','data': result.model_dump()})}\n\n"
            yield f"data: {json.dumps({'type':'done'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type':'error','message':str(e)})}\n\n"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")

# ── Run ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

# ── Proxy Overpass (evita 429 dal browser) ─────────────────────────
class OverpassProxyRequest(BaseModel):
    query: str

@app.post("/api/proxy-overpass")
async def proxy_overpass(request: OverpassProxyRequest):
    """
    Esegue query Overpass server-side con mirror fallback.
    Elimina i 429 Too Many Requests dal frontend.
    """
    import httpx
    mirrors = [
        "https://overpass-api.de/api/interpreter",
        "https://lz4.overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass.openstreetmap.ru/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    ]
    headers = {"User-Agent": "Campera/1.0 travel-app campera.app contact@campera.app"}
    last_err = "no mirrors tried"
    for mirror in mirrors:
        try:
            async with httpx.AsyncClient(timeout=18) as client:
                resp = await client.post(
                    mirror, data={"data": request.query}, headers=headers
                )
                if resp.status_code in (429, 503, 502):
                    last_err = f"HTTP {resp.status_code} da {mirror}"
                    await asyncio.sleep(0.3)
                    continue
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            last_err = str(e)
            continue
    raise HTTPException(503, f"Overpass non disponibile: {last_err}")


# ── Discover POIs for multiple stops (Agent 4 server-side) ────────────────────
class DiscoverPOIsRequest(BaseModel):
    soste: List[dict]          # [{lat, lng, giorno, nome}, ...]
    moods: List[str] = ["natura"]
    con_bambini: bool = False
    con_animali: bool = False

@app.post("/api/discover-pois")
async def api_discover_pois(request: DiscoverPOIsRequest):
    """
    Agent 4 server-side: OSM parallelo per tutte le soste.
    Invece di N soste × M categorie = N*M query seriali nel browser,
    le eseguiamo tutte in asyncio.gather → 5-10s per qualsiasi numero di soste.
    """
    from tools.osm import search_pois_overpass, EMOJI_MAP, _haversine

    MOOD_TO_CATS = {
        "natura":      ["natura", "panorami", "borghi"],
        "storia":      ["attrazioni", "borghi", "panorami"],
        "gastronomia": ["ristoranti", "borghi", "attrazioni"],
        "relax":       ["spiagge", "panorami", "natura"],
        "avventura":   ["natura", "panorami", "attrazioni"],
        "famiglia":    ["attrazioni", "spiagge", "natura"],
        "mare":        ["spiagge", "natura", "panorami"],
        "montagna":    ["natura", "panorami", "attrazioni"],
    }

    # Categorie da cercare per questa sessione
    cats: list = []
    for mood in (request.moods or ["natura"]):
        for c in MOOD_TO_CATS.get(mood, ["attrazioni", "natura", "panorami"]):
            if c not in cats:
                cats.append(c)
    cats = cats[:4]  # max 4 categorie per evitare overhead

    async def _search_stop(sosta: dict):
        lat, lng = sosta.get("lat"), sosta.get("lng")
        if not lat or not lng:
            return {"sostaGiorno": sosta.get("giorno", 0), "pois": [], "gemmeCount": 0}

        # Cerca tutte le categorie in parallelo per questa sosta
        results = await asyncio.gather(*[
            search_pois_overpass(lat, lng, cat, radius_km=20, limit=20)
            for cat in cats
        ], return_exceptions=True)

        all_pois = []
        seen = set()
        for pois in results:
            if isinstance(pois, Exception):
                continue
            for p in (pois or []):
                key = p["nome"].lower().strip()
                if key in seen or len(key) < 3:
                    continue
                seen.add(key)
                all_pois.append(p)

        # Ordina per distanza, prendi top 8
        all_pois.sort(key=lambda x: x.get("distanza_km", 99))
        top = all_pois[:8]
        gemme = sum(1 for p in top if p.get("categoria") in ("borghi", "panorami"))

        # Normalizza per frontend (stesso formato di agents34.js)
        pois_out = [{
            "nome": p["nome"],
            "lat": p["lat"],
            "lng": p["lng"],
            "categoria": p["categoria"],
            "emoji": p.get("emoji", "📍"),
            "distanzaKm": round(p.get("distanza_km", 0), 1),
            "distKm": round(p.get("distanza_km", 0), 1),
            "isGemma": p.get("categoria") in ("borghi", "panorami"),
            "fonte": "osm_backend",
            "compatibilita_motivo": f"{p.get('emoji','📍')} {p.get('categoria','poi')} a {round(p.get('distanza_km',0),1)}km",
        } for p in top]

        return {
            "sostaGiorno": sosta.get("giorno", 0),
            "pois": pois_out,
            "gemmeCount": gemme,
        }

    # Tutte le soste in parallelo
    results = await asyncio.gather(*[_search_stop(s) for s in request.soste], return_exceptions=True)

    output = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            output.append({"sostaGiorno": request.soste[i].get("giorno", i), "pois": [], "gemmeCount": 0})
        else:
            output.append(r)

    return {"stops": output, "total_pois": sum(len(r["pois"]) for r in output)}
