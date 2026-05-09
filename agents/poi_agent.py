from __future__ import annotations
"""
POIAgent — FAST: ricerca OSM parallela + una sola chiamata Claude.
Tempi: ~8-15s invece di 60-90s del loop tool_use.
"""
import json
import asyncio
from anthropic import AsyncAnthropic
from tools.osm import search_pois_overpass, EMOJI_MAP

# Mappa stile → categorie OSM (evita laghi — relazioni enormi, lente)
STILE_CATEGORIE = {
    "natura":      ["natura", "panorami"],
    "storia":      ["attrazioni", "borghi"],
    "gastronomia": ["ristoranti", "borghi"],
    "relax":       ["spiagge", "panorami", "natura"],
    "avventura":   ["natura", "panorami"],
    "famiglia":    ["attrazioni", "spiagge", "natura"],
    "default":     ["attrazioni", "natura", "panorami"],
}

SYSTEM_PROMPT = """Sei l'agente POI di Campera, un'app per viaggiatori in camper italiani.
Ti vengono forniti POI trovati vicino a una sosta. Il tuo compito:
- Seleziona i 3-4 highlights più rilevanti e interessanti per questo utente
- Considera il profilo (stili, bambini, animali, budget)
- Dai priorità a luoghi unici e autentici (no catene commerciali)
- Includi almeno: 1 posto naturale/panorama + 1 cosa "da non perdere" locale

Rispondi SOLO con questo JSON (niente altro testo):
{
  "highlights": [
    {
      "nome": "...",
      "lat": 0.0,
      "lng": 0.0,
      "categoria": "...",
      "emoji": "...",
      "motivazione": "...",
      "distanza_km": 0.0
    }
  ],
  "consiglio_zona": "..."
}"""

# Nomi fallback per POI senza tag "name"
FALLBACK_NAMES = {
    "panorami":  "Punto Panoramico",
    "natura":    "Area Naturale",
    "spiagge":   "Spiaggia",
    "attrazioni": "Attrazione",
    "borghi":    "Borgo Storico",
}


async def curate_pois_for_stop(
    lat: float,
    lng: float,
    nome_sosta: str,
    profilo: dict,
    anthropic_client: AsyncAnthropic,
    model: str = "claude-sonnet-4-5",
) -> dict:
    """FAST PATH: OSM parallelo → una sola chiamata Claude."""
    stili   = profilo.get("stili", ["natura"])
    con_bambini = profilo.get("con_bambini", False)
    con_animali = profilo.get("con_animali", False)
    budget  = profilo.get("budget", "medio")

    # 1. Categorie de-duplicate (max 4)
    cats: list[str] = []
    for s in stili:
        for c in STILE_CATEGORIE.get(s, STILE_CATEGORIE["default"]):
            if c not in cats:
                cats.append(c)
    cats = (cats or STILE_CATEGORIE["default"])[:4]

    # 2. Ricerca Overpass parallela (timeout ridotto a 10s per categoria)
    async def safe_search(cat):
        try:
            return await asyncio.wait_for(
                search_pois_overpass(lat, lng, cat, radius_km=12, limit=15),
                timeout=12.0
            )
        except Exception as e:
            print(f"[POIAgent] {cat} timeout/err: {e}")
            return []

    tasks = [safe_search(cat) for cat in cats]
    results_per_cat = await asyncio.gather(*tasks, return_exceptions=True)

    # 3. Aggrega con fallback nomi
    all_pois: list[dict] = []
    seen_names: set[str] = set()
    for cat, res in zip(cats, results_per_cat):
        if isinstance(res, Exception):
            print(f"[POIAgent] OSM error {cat}: {res}")
            continue
        for p in res:
            nome = p.get("nome") or FALLBACK_NAMES.get(cat)
            if not nome or nome in seen_names:
                continue
            seen_names.add(nome)
            all_pois.append({
                "nome": nome,
                "lat":  p["lat"],
                "lng":  p["lng"],
                "categoria": cat,
                "emoji": EMOJI_MAP.get(cat, "📍"),
                "distanza_km": round(p["distanza_km"], 1),
            })

    if not all_pois:
        return {"highlights": [], "consiglio_zona": "Zona tranquilla, ideale per riposare."}

    all_pois.sort(key=lambda x: x["distanza_km"])
    all_pois = all_pois[:30]

    # 4. Una sola chiamata Claude
    user_msg = (
        f"Sosta: {nome_sosta} ({lat:.4f}, {lng:.4f})\n"
        f"Profilo: stili={','.join(stili)} | bambini={'sì' if con_bambini else 'no'}"
        f" | animali={'sì' if con_animali else 'no'} | budget={budget}\n\n"
        f"POI trovati nelle vicinanze:\n"
        f"{json.dumps(all_pois, ensure_ascii=False, indent=2)}\n\n"
        f"Seleziona i 3-4 highlights migliori per questo utente."
    )

    try:
        response = await anthropic_client.messages.create(
            model=model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = response.content[0].text if response.content else ""
        start = text.find("{")
        end   = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    except Exception as e:
        print(f"[POIAgent] Claude error: {e}")

    return {"highlights": [], "consiglio_zona": ""}
