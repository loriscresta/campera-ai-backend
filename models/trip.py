from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, List, Any

# Mapping: frontend mood → backend stile normalizzato
# Accetta qualsiasi stringa — Claude capisce il contesto
MOOD_ALIASES: dict[str, str] = {
    "montagna":    "avventura",
    "mare":        "relax",
    "lago":        "relax",
    "storia":      "cultura",
    "arte":        "cultura",
    "borghi":      "cultura",
    "sport":       "avventura",
    "trekking":    "avventura",
    "enogastr":    "gastronomia",
    "food":        "gastronomia",
    "bambini":     "famiglia",
    "family":      "famiglia",
}

VALID_STILI = {"avventura", "relax", "cultura", "natura", "gastronomia", "famiglia"}

def normalize_stili(stili: List[str]) -> List[str]:
    result = []
    for s in stili:
        s_lower = s.lower().strip()
        if s_lower in VALID_STILI:
            result.append(s_lower)
        elif s_lower in MOOD_ALIASES:
            result.append(MOOD_ALIASES[s_lower])
        else:
            # Fallback: prova a trovare un match parziale
            matched = next((v for k, v in MOOD_ALIASES.items() if k in s_lower or s_lower in k), None)
            result.append(matched or "natura")
    return list(dict.fromkeys(result)) or ["natura"]  # dedupe, default natura

class UserProfile(BaseModel):
    stili: List[str] = ["natura"]   # accetta qualsiasi stringa — normalizzata internamente
    budget: str = "medio"           # basso / medio / alto
    tipo_camper: str = "camper"     # camper / van / caravan
    con_animali: bool = False
    con_bambini: bool = False
    preferenze_note: str = ""
    km_max_giorno: Optional[int] = None
    camper_lunghezza_m: Optional[float] = None

class Coordinate(BaseModel):
    lat: float
    lng: float
    nome: str = ""

class TripRequest(BaseModel):
    partenza: Coordinate
    destinazione: Coordinate
    num_giorni: int = Field(ge=1, le=21)
    profilo: UserProfile = UserProfile()
    waypoints: List[Coordinate] = []
    data_partenza: Optional[str] = None   # "2025-06-15"

class Sosta(BaseModel):
    giorno: int
    nome: str
    lat: float
    lng: float
    km_da_precedente: Optional[float] = None
    km_totali_percorsi: Optional[float] = None
    tipo: str = "overnight"        # overnight / destinazione
    servizi: dict = {}
    ai_racconto: str = ""
    highlights: List[dict] = []    # POI curati dall'AI
    meteo: Optional[dict] = None

class TripResponse(BaseModel):
    trip_id: str
    titolo: str
    sommario: str
    num_giorni: int
    km_totali: float
    soste: List[Sosta]
    route_geojson: Optional[dict] = None
    consigli_generali: str = ""
    status: str = "ok"
    warnings: List[str] = []
