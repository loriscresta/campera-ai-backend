/**
 * camperaBackend.js — Connector per il Campera AI Backend
 * 
 * Drop-in replacement per le chiamate all'orchestratore Base44.
 * Sostituisce la logica AI limitata con il backend esterno Claude.
 * 
 * Setup: dopo il deploy Railway, aggiorna BACKEND_URL sotto.
 */

const BACKEND_URL = 
  (typeof import !== 'undefined' && import.meta?.env?.VITE_CAMPERA_BACKEND_URL) ||
  'https://campera-backend.up.railway.app';  // ← aggiorna dopo il deploy

/**
 * Genera un viaggio completo via AI backend.
 * Output compatibile con il formato orchestratore Base44.
 */
export async function generateTripFromBackend({
  partenzaLat, partenzaLng, partenzaNome,
  destinazioneLat, destinazioneLng, destinazioneNome,
  numGiorni, profilo = {}, dataPartenza = null,
}) {
  const resp = await fetch(`${BACKEND_URL}/api/generate-trip`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      partenza: { lat: partenzaLat, lng: partenzaLng, nome: partenzaNome },
      destinazione: { lat: destinazioneLat, lng: destinazioneLng, nome: destinazioneNome },
      num_giorni: numGiorni,
      profilo: {
        stili: profilo.stili || ['natura'],
        budget: profilo.budget || 'medio',
        tipo_camper: profilo.tipo_camper || 'camper',
        con_animali: profilo.con_animali || false,
        con_bambini: profilo.con_bambini || false,
      },
      data_partenza: dataPartenza,
    }),
  });

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || `Backend error ${resp.status}`);
  }

  const data = await resp.json();

  // Converti nel formato che CamperaMap.jsx si aspetta
  return {
    trip: { id: data.trip_id, titolo: data.titolo, sommario: data.sommario },
    sosteNotturne: data.soste.map(s => ({
      giorno: s.giorno,
      nome: s.nome,
      lat: s.lat,
      lng: s.lng,
      servizi: s.servizi || {},
      ai_racconto: s.ai_racconto || '',
      poi_nei_dintorni: s.highlights || [],
      meteo: s.meteo || null,
      km_da_precedente: s.km_da_precedente,
    })),
    route: { routeGeoJSON: data.route_geojson, geometry: data.route_geojson },
    stops: data.soste,
    warnings: data.warnings || [],
  };
}

/**
 * Cura i POI per una sosta al momento del load viaggio.
 * Chiama Claude che ragiona e seleziona i 3-4 highlights migliori.
 */
export async function curatePOIsForStop({ lat, lng, nome, profilo = {} }) {
  const resp = await fetch(`${BACKEND_URL}/api/curate-pois`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      lat, lng, nome,
      stili: profilo.stili || ['natura'],
      con_bambini: profilo.con_bambini || false,
      con_animali: profilo.con_animali || false,
      budget: profilo.budget || 'medio',
    }),
  });
  if (!resp.ok) return { highlights: [], consiglio_zona: '' };
  return resp.json();
}

export async function checkBackendHealth() {
  try {
    const resp = await fetch(`${BACKEND_URL}/api/health`);
    return resp.ok ? await resp.json() : null;
  } catch { return null; }
}
