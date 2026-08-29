// Lettore ZIP minimale, per estrarre i risultati del blocco senza dipendenze.
//
// Il server comprime con ZIP_STORED (i PNG e i WEBP sono gia' compressi), ma
// il metodo "deflate" e' gestito comunque tramite DecompressionStream, cosi'
// un domani cambiare la compressione lato server non rompe l'interfaccia.

const FIRMA_EOCD = 0x06054b50
const FIRMA_VOCE = 0x02014b50

function trovaEocd(vista) {
  // L'EOCD sta in fondo, dopo un commento di lunghezza variabile (max 64 KB).
  const minimo = Math.max(0, vista.byteLength - 65557)
  for (let i = vista.byteLength - 22; i >= minimo; i--) {
    if (vista.getUint32(i, true) === FIRMA_EOCD) return i
  }
  throw new Error('Archivio non valido: fine dello ZIP non trovata')
}

async function estrai(buffer, offsetLocale, dimensione, metodo) {
  const vista = new DataView(buffer)
  // Nell'intestazione locale i due campi di lunghezza stanno a offset 26 e 28.
  const lunghezzaNome = vista.getUint16(offsetLocale + 26, true)
  const lunghezzaExtra = vista.getUint16(offsetLocale + 28, true)
  const inizio = offsetLocale + 30 + lunghezzaNome + lunghezzaExtra
  const dati = buffer.slice(inizio, inizio + dimensione)
  if (metodo === 0) return dati
  if (metodo === 8) {
    const flusso = new Blob([dati]).stream().pipeThrough(new DecompressionStream('deflate-raw'))
    return await new Response(flusso).arrayBuffer()
  }
  throw new Error(`Metodo di compressione non gestito: ${metodo}`)
}

/** Legge uno ZIP e restituisce una mappa nome -> Blob. */
export async function leggiZip(blob, tipiPerEstensione = {}) {
  const buffer = await blob.arrayBuffer()
  const vista = new DataView(buffer)
  const eocd = trovaEocd(vista)
  const voci = vista.getUint16(eocd + 10, true)
  let offset = vista.getUint32(eocd + 16, true)

  const decoder = new TextDecoder()
  const contenuto = new Map()
  for (let i = 0; i < voci; i++) {
    if (vista.getUint32(offset, true) !== FIRMA_VOCE) {
      throw new Error('Archivio non valido: voce inattesa')
    }
    const metodo = vista.getUint16(offset + 10, true)
    const dimensione = vista.getUint32(offset + 20, true)
    const lunghezzaNome = vista.getUint16(offset + 28, true)
    const lunghezzaExtra = vista.getUint16(offset + 30, true)
    const lunghezzaCommento = vista.getUint16(offset + 32, true)
    const offsetLocale = vista.getUint32(offset + 42, true)
    const nome = decoder.decode(new Uint8Array(buffer, offset + 46, lunghezzaNome))

    const dati = await estrai(buffer, offsetLocale, dimensione, metodo)
    const estensione = nome.split('.').pop()?.toLowerCase() ?? ''
    contenuto.set(nome, new Blob([dati], { type: tipiPerEstensione[estensione] ?? '' }))
    offset += 46 + lunghezzaNome + lunghezzaExtra + lunghezzaCommento
  }
  return contenuto
}
