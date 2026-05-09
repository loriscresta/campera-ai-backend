from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, List, Any
from enum import Enum

class TravelStyle(str, Enum):
    avventura = "avventura"
    relax = "relax"
    cultura = "cultura"
    natura = "natura"
    gastronomia = "gastronomia"
    famiglia = "famiglia"

class UserProfile(BaseModel):
    stili: List[TravelStyle] = [TravelStyle.natura]
    budget: str = "medio"          # basso / medio / alto
    tipo_camper: str = "camper"    # camper / van / caravan
    con_animali: bool = False
    con_bambini: bool = False
    preferenze_note: str = ""

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
