"""
NarratorAgent — Genera il racconto coinvolgente per ogni tappa del viaggio.

Non è una descrizione turistica generica: sa dove sei, cosa hai visto,
che tempo fa, e racconta come un amico che conosce bene quella zona.
"""
from anthropic import AsyncAnthropic

SYSTEM_PROMPT = """Sei il narratore di Campera, un'app per camperisti italiani.
Scrivi il racconto di ogni tappa del viaggio — breve, coinvolgente, personale.

TONO: come un amico che ha già percorso quella strada e ti racconta cosa ti aspetta.
Non sei una guida turistica. Non usi frasi come "questa zona è ricca di..." 
Non elenchi. Racconti.

STRUTTURA del racconto (max 120 parole):
- Apertura visiva: descrivi il paesaggio che si vedrà arrivando
- Il momento clou: la cosa che ricorderai di questa tappa
- Consiglio pratico: un piccolo suggerimento da insider (orario, posto dove fermarsi, cosa evitare)

Usa un linguaggio caldo, italiano contemporaneo, con qualche aggettivo preciso.
Niente superlativi vuoti. Niente "meravigliosa" o "bellissima" da soli — mostra, non dire."""

async def generate_tappa_narrative(
    giorno: int,
    nome_sosta: str,
    km_giornata: float,
    highlights: list[dict],
    meteo: dict,
    profilo: dict,
    zona_descrizione: str,
    anthropic_client: AsyncAnthropic,
    model: str = "claude-sonnet-4-5"
) -> str:
    """Genera il racconto per una tappa specifica."""
    
    highlights_txt = ""
    if highlights:
        highlights_txt = "POI nella zona:\n" + "\n".join(
            f"- {h['emoji']} {h['nome']}: {h.get('motivazione','')}"
            for h in highlights[:4]
        )
    
    meteo_txt = ""
    if meteo:
        meteo_txt = f"Meteo previsto: {meteo.get('descrizione','')} {meteo.get('emoji','')} | {meteo.get('t_max','?')}°/{meteo.get('t_min','?')}°C"
    
    prompt = f"""Giorno {giorno}: tappa verso {nome_sosta}
Distanza giornaliera: ~{km_giornata:.0f} km
{meteo_txt}
{highlights_txt}
{"Carattere della zona: " + zona_descrizione if zona_descrizione else ""}
Profilo viaggiatore: {', '.join(profilo.get('stili', ['natura']))}

Scrivi il racconto di questa tappa (max 120 parole)."""

    response = await anthropic_client.messages.create(
        model=model,
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    
    for block in response.content:
        if hasattr(block, "text"):
            return block.text.strip()
    return ""

async def generate_trip_summary(
    partenza: str,
    destinazione: str,
    num_giorni: int,
    km_totali: float,
    soste: list[dict],
    profilo: dict,
    anthropic_client: AsyncAnthropic,
    model: str = "claude-sonnet-4-5"
) -> tuple[str, str]:
    """Genera titolo e sommario del viaggio completo."""
    
    soste_txt = " → ".join(s.get("nome","") for s in soste[:6])
    
    prompt = f"""Viaggio in camper: {partenza} → {destinazione}
{num_giorni} giorni, {km_totali:.0f} km totali
Soste: {soste_txt}
Stile: {', '.join(profilo.get('stili', ['natura']))}

Genera:
1. TITOLO: un titolo evocativo del viaggio (max 8 parole, non banale)
2. SOMMARIO: 2-3 frasi che catturano l'essenza del percorso (max 60 parole)

Rispondi SOLO nel formato:
TITOLO: ...
SOMMARIO: ..."""

    response = await anthropic_client.messages.create(
        model=model,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    
    titolo = f"Viaggio {partenza} → {destinazione}"
    sommario = ""
    
    for block in response.content:
        if hasattr(block, "text"):
            lines = block.text.strip().split("\n")
            for line in lines:
                if line.startswith("TITOLO:"):
                    titolo = line.replace("TITOLO:", "").strip()
                elif line.startswith("SOMMARIO:"):
                    sommario = line.replace("SOMMARIO:", "").strip()
    
    return titolo, sommario
