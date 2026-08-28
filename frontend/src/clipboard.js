// Copia dell'immagine negli appunti. Gli appunti dei browser accettano
// praticamente solo image/png: un WEBP va riconvertito prima, altrimenti
// navigator.clipboard.write rifiuta il tipo.

export function supportaCopia() {
  return typeof ClipboardItem !== 'undefined' && Boolean(navigator.clipboard?.write)
}

/** Ridisegna un blob su canvas e lo riesporta in PNG, conservando la trasparenza. */
export function convertiInPng(blob) {
  return new Promise((risolvi, rifiuta) => {
    const url = URL.createObjectURL(blob)
    const img = new Image()
    img.onload = () => {
      const canvas = document.createElement('canvas')
      canvas.width = img.naturalWidth
      canvas.height = img.naturalHeight
      canvas.getContext('2d').drawImage(img, 0, 0)
      URL.revokeObjectURL(url)
      canvas.toBlob((png) => (png ? risolvi(png) : rifiuta(new Error('Conversione fallita'))), 'image/png')
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      rifiuta(new Error('Immagine non leggibile'))
    }
    img.src = url
  })
}

/** Copia l'immagine negli appunti come PNG.
 *
 * Il ClipboardItem riceve una promessa invece del blob gia' pronto: Safari
 * annulla la scrittura se fra il clic e la write c'e' un await.
 */
export async function copiaImmagine(blob, { converti = convertiInPng } = {}) {
  if (!supportaCopia()) {
    throw new Error('Il tuo browser non permette di copiare immagini negli appunti')
  }
  const png = blob.type === 'image/png' ? Promise.resolve(blob) : converti(blob)
  try {
    await navigator.clipboard.write([new ClipboardItem({ 'image/png': png })])
  } catch (err) {
    // Il browser blocca la scrittura se la pagina non ha il fuoco o se il
    // permesso e' negato: il messaggio nativo e' incomprensibile all'utente.
    if (err?.name === 'NotAllowedError') {
      throw new Error('Copia bloccata dal browser: clicca sulla pagina e riprova')
    }
    throw new Error('Copia non riuscita')
  }
}
