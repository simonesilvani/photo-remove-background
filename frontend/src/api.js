// In sviluppo le richieste passano dal proxy Vite; in produzione si imposta VITE_API_URL.
const BASE = import.meta.env.VITE_API_URL ?? ''

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

export async function removeBackground({ file, model, alphaMatting, background, signal }) {
  const form = new FormData()
  form.append('file', file)
  form.append('model', model)
  form.append('alpha_matting', String(alphaMatting))
  if (background) form.append('background', background)

  const res = await fetch(`${BASE}/api/remove-background`, {
    method: 'POST',
    body: form,
    signal,
  })

  if (!res.ok) {
    throw new Error(await messaggioErrore(res))
  }

  const blob = await res.blob()
  return {
    url: URL.createObjectURL(blob),
    blob,
    elapsed: Number(res.headers.get('X-Processing-Time')) || null,
    width: Number(res.headers.get('X-Image-Width')) || null,
    height: Number(res.headers.get('X-Image-Height')) || null,
  }
}
