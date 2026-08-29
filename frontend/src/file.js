// Normalizzazione dei file scelti dall'utente, prima di spedirli.

// Estensione -> tipo MIME, per i file che arrivano senza `type` valorizzato:
// succede spesso con le immagini esportate dalla libreria Foto.
export const TIPI = {
  jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png',
  webp: 'image/webp', bmp: 'image/bmp', tif: 'image/tiff', tiff: 'image/tiff',
  heic: 'image/heic', heif: 'image/heif', avif: 'image/avif',
}

/** Rilegge il file in memoria e ne normalizza il tipo.
 *
 * I byte si leggono alla selezione, non al momento dell'invio: le immagini
 * della libreria Foto sono file temporanei che possono sparire nel frattempo.
 * Se succede mentre la richiesta e' in corso, il browser tronca il corpo e al
 * server non arriva piu' niente — nemmeno gli altri campi del modulo.
 */
export async function preparaFile(next, { maxBytes = Infinity } = {}) {
  const nome = next.name || 'immagine'
  if (next.size > maxBytes) {
    throw new Error(`${nome}: troppo grande, il limite e’ ${Math.round(maxBytes / 1024 / 1024)} MB`)
  }

  let bytes
  try {
    bytes = await next.arrayBuffer()
  } catch {
    throw new Error(
      `${nome}: impossibile leggerlo. Se viene dall’app Foto, esportalo sul disco e riprova.`
    )
  }
  if (!bytes.byteLength) {
    throw new Error(`${nome}: vuoto o non più disponibile`)
  }

  const estensione = nome.split('.').pop()?.toLowerCase() ?? ''
  const tipo = next.type || TIPI[estensione] || 'application/octet-stream'
  return new File([bytes], nome, { type: tipo })
}

/** Prepara piu' file, separando quelli utilizzabili dai problemi incontrati. */
export async function preparaFiles(lista, opzioni) {
  const pronti = []
  const problemi = []
  for (const f of lista) {
    try {
      pronti.push(await preparaFile(f, opzioni))
    } catch (err) {
      problemi.push(err.message)
    }
  }
  return { pronti, problemi }
}
