from __future__ import annotations
"""
Meteo per ogni tappa via Open-Meteo (gratuito, nessuna API key richiesta).
"""
import httpx
from datetime import datetime, timedelta

async def get_weather_for_stop(
    lat: float, lng: float, 
    date_str: Optional[str] = None
) -> dict:
    """
    Meteo per una sosta specifica.
    Se date_str non specificato, usa previsione a 7 giorni.
    """
    from typing import Optional
    
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lng,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode,windspeed_10m_max",
        "timezone": "Europe/Rome",
        "forecast_days": 7,
    }
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            daily = data.get("daily", {})
            dates = daily.get("time", [])
            if not dates:
                return {}
            
            # Prendi il primo giorno disponibile (o quello target)
            idx = 0
            if date_str and date_str in dates:
                idx = dates.index(date_str)
            
            wmo = daily.get("weathercode", [None])[idx]
            return {
                "data": dates[idx],
                "t_max": daily.get("temperature_2m_max", [None])[idx],
                "t_min": daily.get("temperature_2m_min", [None])[idx],
                "pioggia_prob": daily.get("precipitation_probability_max", [None])[idx],
                "vento_max": daily.get("windspeed_10m_max", [None])[idx],
                "codice": wmo,
                "descrizione": _wmo_to_text(wmo),
                "emoji": _wmo_to_emoji(wmo),
            }
    except Exception as e:
        print(f"[Weather] error: {e}")
        return {}

def _wmo_to_text(code: Optional[int]) -> str:
    if code is None: return "N/D"
    if code == 0: return "Sereno"
    if code in (1,2,3): return "Parzialmente nuvoloso"
    if code in (45,48): return "Nebbia"
    if code in (51,53,55): return "Pioggerella"
    if code in (61,63,65): return "Pioggia"
    if code in (71,73,75): return "Neve"
    if code in (80,81,82): return "Rovesci"
    if code in (95,96,99): return "Temporale"
    return "Variabile"

def _wmo_to_emoji(code: Optional[int]) -> str:
    if code is None: return "🌤️"
    if code == 0: return "☀️"
    if code in (1,2,3): return "⛅"
    if code in (45,48): return "🌫️"
    if code in (51,53,55,61,63,65,80,81,82): return "🌧️"
    if code in (71,73,75): return "❄️"
    if code in (95,96,99): return "⛈️"
    return "🌤️"

