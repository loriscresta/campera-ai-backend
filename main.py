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
        "https://overpass.kumi.systems/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    ]
    last_err = None
    for mirror in mirrors:
        try:
            async with httpx.AsyncClient(timeout=28) as client:
                resp = await client.post(mirror, data={"data": request.query})
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            last_err = str(e)
            continue
    raise HTTPException(503, f"Overpass non disponibile: {last_err}")
