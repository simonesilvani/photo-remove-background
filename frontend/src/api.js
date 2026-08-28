// In sviluppo le richieste passano dal proxy Vite; in produzione si imposta VITE_API_URL.
const BASE = import.meta.env.VITE_API_URL ?? ''

export async function fetchLimits() {
  const res = await fetch(`${BASE}/api/health`)
  if (!res.ok) throw new Error('Backend non raggiungibile')
  return (await res.json()).limits
}

export async function fetchModels() {
  const res = await fetch(`${BASE}/api/models`)
  if (!res.ok) throw new Error('Impossibile caricare la lista dei modelli')
  return res.json()
}

/** Estrae un messaggio leggibile da una risposta di errore: `detail` e' una
 * stringa per gli errori dell'applicazione, ma una lista di oggetti per quelli
 * di validazione di FastAPI.
 */
async function messaggioErrore(res) {
  let body
  try {
    body = await res.json()
  } catch {
    return `Errore ${res.status} ${res.statusText}`.trim()
  }

  const detail = body?.detail
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail)) {
    const righe = detail.map((e) => {
      const campo = (e?.loc ?? []).filter((p) => p !== 'body').join('.')
      const msg = e?.msg ?? 'valore non valido'
      return campo ? `${campo}: ${msg}` : msg
    })
    if (righe.length) return righe.join('; ')
  }
  if (detail) return JSON.stringify(detail)
  return `Errore ${res.status}`
}

// Oltre questo tempo la richiesta viene abbandonata: senza, se il backend muore
// a meta' elaborazione la rotella gira per sempre.
const TIMEOUT_MS = 180_000

export async function removeBackground({
  file,
  model,
  alphaMatting,
  background,
  formato,
  trim,
  signal,
  timeoutMs = TIMEOUT_MS,
}) {
  const form = new FormData()
  form.append('file', file)
  form.append('model', model)
  form.append('alpha_matting', String(alphaMatting))
  form.append('format', formato)
  form.append('trim', String(Boolean(trim)))
  if (background) form.append('background', background)

  // Il segnale del chiamante (annullamento manuale) e quello del timeout
  // vengono uniti: scatta il primo dei due.
  const scadenza = AbortSignal.timeout(timeoutMs)
  const segnale = signal ? AbortSignal.any([signal, scadenza]) : scadenza

  let res
  try {
    res = await fetch(`${BASE}/api/remove-background`, {
      method: 'POST',
      body: form,
      signal: segnale,
    })
  } catch (err) {
    if (scadenza.aborted) {
      throw new Error('Il server non ha risposto in tempo. Riprova.')
    }
    throw err
  }

  if (!res.ok) {
    throw new Error(await messaggioErrore(res))
  }

  const blob = await res.blob()
  return {
    url: URL.createObjectURL(blob),
    blob,
    formato,
    elapsed: Number(res.headers.get('X-Processing-Time')) || null,
    width: Number(res.headers.get('X-Image-Width')) || null,
    height: Number(res.headers.get('X-Image-Height')) || null,
  }
}
