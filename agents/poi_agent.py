"""
POIAgent — Il cuore dell'intelligenza di Campera.

Dato una sosta (lat/lng) e il profilo utente, usa Claude con tool_use
per selezionare i 3-4 highlights più rilevanti nella zona.
Non è una lista bruta: Claude ragiona su cosa vale davvero la pena vedere.
"""
import json
import asyncio
from anthropic import AsyncAnthropic
from tools.osm import search_pois_overpass, EMOJI_MAP

TOOL_DEFINITIONS = [
    {
        "name": "search_pois",
        "description": "Cerca POI (punti di interesse) in una zona tramite OpenStreetMap. Restituisce una lista di luoghi con nome, categoria, distanza e tag OSM.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitudine del centro di ricerca"},
                "lng": {"type": "number", "description": "Longitudine del centro di ricerca"},
                "categoria": {
                    "type": "string",
                    "description": "Categoria OSM da cercare",
                    "enum": ["campeggi", "aree_sosta", "attrazioni", "natura", "panorami",
                             "ristoranti", "spiagge", "supermercati", "borghi", "laghi"]
                },
                "radius_km": {"type": "number", "description": "Raggio di ricerca in km (default 15)", "default": 15},
            },
            "required": ["lat", "lng", "categoria"]
        }
    }
]

SYSTEM_PROMPT = """Sei l'agente POI di Campera, un'app per viaggiatori in camper.
Il tuo compito è selezionare i 3-4 punti di interesse più rilevanti e interessanti 
per una specifica sosta, basandoti sul profilo dell'utente.

REGOLE:
1. Usa lo strumento search_pois per cercare POI in diverse categorie
2. Scegli SOLO quello che vale davvero la pena - qualità > quantità
3. Adatta la selezione al profilo utente (stile viaggio, interessi, famiglia, animali)
4. Dai priorità a luoghi unici, poco conosciuti ma autentici
5. Includi sempre almeno: 1 posto naturale/panorama + 1 cosa "da non perdere" locale
6. Evita catene commerciali o luoghi banali (no McDonald's, no centri commerciali)
7. Aggiungi una breve motivazione in italiano per ogni POI scelto (1-2 frasi coinvolgenti)

Output FINALE (dopo le ricerche): un JSON con questa struttura:
{
  "highlights": [
    {
      "nome": "...",
      "lat": 0.0,
      "lng": 0.0,
      "categoria": "...",
      "emoji": "...",
      "motivazione": "...",  // perché l'AI lo consiglia - tono caldo, non da guida turistica
      "distanza_km": 0.0,
      "tags": {}
    }
  ],
  "consiglio_zona": "..."  // una frase sul carattere della zona, tono da amico che conosce il posto
}"""

async def curate_pois_for_stop(
    lat: float, 
    lng: float, 
    nome_sosta: str,
    profilo: dict,
    anthropic_client: AsyncAnthropic,
    model: str = "claude-sonnet-4-5"
) -> dict:
    """
    Claude ragiona su quali POI mostrare per questa sosta.
    Usa tool_use per cercare e poi seleziona i migliori.
    """
    
    stili = profilo.get("stili", ["natura"])
    con_bambini = profilo.get("con_bambini", False)
    con_animali = profilo.get("con_animali", False)
    budget = profilo.get("budget", "medio")
    
    user_msg = f"""Sosta: {nome_sosta} (lat:{lat:.4f}, lng:{lng:.4f})

Profilo utente:
- Stili preferiti: {', '.join(stili)}
- Con bambini: {'sì' if con_bambini else 'no'}
- Con animali: {'sì' if con_animali else 'no'}  
- Budget: {budget}

Cerca i POI più rilevanti intorno a questa sosta e seleziona i 3-4 highlights.
Considera il profilo utente nella selezione. Cerca in almeno 3 categorie diverse."""

    messages = [{"role": "user", "content": user_msg}]
    
    # Agent loop con tool_use
    for _ in range(6):  # max 6 round-trip (cerca in ~3 categorie + elabora)
        response = await anthropic_client.messages.create(
            model=model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )
        
        messages.append({"role": "assistant", "content": response.content})
        
        if response.stop_reason == "end_turn":
            # Estrai JSON dall'ultima risposta
            for block in response.content:
                if hasattr(block, "text"):
                    try:
                        # Cerca JSON nel testo
                        text = block.text
                        start = text.find("{")
                        end = text.rfind("}") + 1
                        if start >= 0 and end > start:
                            return json.loads(text[start:end])
                    except:
                        pass
            return {"highlights": [], "consiglio_zona": ""}
        
        if response.stop_reason != "tool_use":
            break
        
        # Esegui i tool call
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = await _execute_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })
        
        if tool_results:
            messages.append({"role": "user", "content": tool_results})
    
    return {"highlights": [], "consiglio_zona": ""}

async def _execute_tool(name: str, inputs: dict) -> list:
    """Esegue un tool call e restituisce il risultato."""
    if name == "search_pois":
        results = await search_pois_overpass(
            lat=inputs["lat"],
            lng=inputs["lng"],
            categoria=inputs["categoria"],
            radius_km=inputs.get("radius_km", 15),
        )
        # Restituisce un sottoinsieme pulito per Claude
        return [
            {
                "nome": p["nome"],
                "lat": p["lat"],
                "lng": p["lng"],
                "categoria": p["categoria"],
                "emoji": p.get("emoji", "📍"),
                "distanza_km": round(p["distanza_km"], 1),
                "tags": p.get("tags", {}),
            }
            for p in results[:15]  # max 15 per non sovraccaricare il contesto
        ]
    return []
