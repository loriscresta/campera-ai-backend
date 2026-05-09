"""
CampsiteAgent — Sceglie la sosta notturna migliore per ogni giorno.

Supera la logica statica di agents34.js: Claude ragiona su km, servizi,
meteo, preferenze utente e trova il posto giusto, non solo il più vicino.
"""
import json
from anthropic import AsyncAnthropic
from tools.osm import search_campsites_near_point, _haversine

TOOL_DEFINITIONS = [
    {
        "name": "search_campsites",
        "description": "Cerca campeggi e aree sosta camper vicino a un punto sul percorso.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number"},
                "lng": {"type": "number"},
                "radius_km": {"type": "number", "default": 20},
            },
            "required": ["lat", "lng"]
        }
    }
]

SYSTEM_PROMPT = """Sei l'agente campsite di Campera. Scegli la sosta notturna migliore 
per un camperista dato il percorso e le preferenze.

CRITERI DI SCELTA (in ordine di priorità):
1. Deve essere raggiungibile a fine giornata (±30% della tappa pianificata)
2. Preferisci luoghi con servizi (acqua, scarico, elettricità) se budget medio/alto
3. Considera il contesto: vicino a un lago/panorama vale qualche km in più
4. Evita aree industriali o senza appeal — il viaggiatore deve stare bene
5. Per famiglie con bambini: strutture attrezzate > sosta libera
6. Per chi ama la natura: sosta libera in posto bello > campeggio attrezzato in posto banale

Output FINALE come JSON:
{
  "nome": "...",
  "lat": 0.0,
  "lng": 0.0,
  "tipo": "campeggio|area_sosta|sosta_libera",
  "motivo_scelta": "...",
  "servizi_presenti": [],
  "km_dalla_tappa_ideale": 0.0,
  "rating_confidenza": 0.0  // 0-1, quanto sei sicuro della scelta
}
Se non trovi nulla di buono, rispondi con {"fallback": true, "lat": <punto_interpolato>, "lng": <punto_interpolato>}"""

async def find_best_campsite(
    target_lat: float,
    target_lng: float,
    target_km: float,
    giorno: int,
    profilo: dict,
    anthropic_client: AsyncAnthropic,
    model: str = "claude-sonnet-4-5"
) -> dict:
    """
    Trova la sosta migliore vicino al punto target del percorso.
    """
    stili = profilo.get("stili", ["natura"])
    con_bambini = profilo.get("con_bambini", False)
    budget = profilo.get("budget", "medio")

    user_msg = f"""Giorno {giorno} del viaggio. 
Punto target sul percorso: lat={target_lat:.4f}, lng={target_lng:.4f} (km {target_km:.0f} totali percorsi).

Profilo:
- Stili: {', '.join(stili)}
- Con bambini: {'sì' if con_bambini else 'no'}
- Budget: {budget}

Cerca campeggi e aree sosta nella zona e scegli il migliore.
Puoi cercare con radius_km fino a 25 km se necessario."""

    messages = [{"role": "user", "content": user_msg}]

    for _ in range(4):
        response = await anthropic_client.messages.create(
            model=model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    text = block.text
                    start = text.find("{")
                    end = text.rfind("}") + 1
                    if start >= 0 and end > start:
                        try:
                            return json.loads(text[start:end])
                        except:
                            pass
            return {"fallback": True, "lat": target_lat, "lng": target_lng}

        if response.stop_reason != "tool_use":
            break

        tool_results = []
        for block in response.content:
            if block.type == "tool_use" and block.name == "search_campsites":
                inp = block.input
                results = await search_campsites_near_point(
                    inp["lat"], inp["lng"], inp.get("radius_km", 20)
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(results[:20], ensure_ascii=False),
                })
        if tool_results:
            messages.append({"role": "user", "content": tool_results})

    return {"fallback": True, "lat": target_lat, "lng": target_lng}
