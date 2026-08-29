// ZIP minimale, senza dipendenze: la scrittura serve a impacchettare i
// risultati del blocco per il download, la lettura ad aprire gli archivi che
// arrivano dall'endpoint /batch.
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

/** Legge uno ZIP e restituisce una mappa nome -> Blob.
 *
 * Serve a chi consuma l'endpoint /batch, che risponde con un archivio; nei
 * test verifica anche che quello che scriviamo sia rileggibile.
 */
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


// --- scrittura -------------------------------------------------------------

const TABELLA_CRC = (() => {
  const t = new Uint32Array(256)
  for (let i = 0; i < 256; i++) {
    let c = i
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    t[i] = c >>> 0
  }
  return t
})()

function crc32(byte) {
  let c = 0xffffffff
  for (let i = 0; i < byte.length; i++) c = TABELLA_CRC[(c ^ byte[i]) & 0xff] ^ (c >>> 8)
  return (c ^ 0xffffffff) >>> 0
}

/** Impacchetta {nome, blob} in uno ZIP senza compressione.
 *
 * I PNG e i WEBP sono gia' compressi: comprimerli di nuovo costerebbe tempo
 * per un guadagno nullo, e senza compressione il formato si scrive in poche
 * righe invece di richiedere una libreria.
 */
export async function creaZip(voci) {
  const codificatore = new TextEncoder()
  const pezzi = []
  const centrale = []
  let offset = 0

  for (const { nome, blob } of voci) {
    const dati = new Uint8Array(await blob.arrayBuffer())
    const nomeBytes = codificatore.encode(nome)
    const crc = crc32(dati)

    const locale = new DataView(new ArrayBuffer(30))
    locale.setUint32(0, 0x04034b50, true) // firma
    locale.setUint16(4, 20, true) // versione minima
    locale.setUint16(8, 0, true) // metodo: nessuna compressione
    locale.setUint32(14, crc, true)
    locale.setUint32(18, dati.length, true)
    locale.setUint32(22, dati.length, true)
    locale.setUint16(26, nomeBytes.length, true)
    pezzi.push(new Uint8Array(locale.buffer), nomeBytes, dati)

    const voce = new DataView(new ArrayBuffer(46))
    voce.setUint32(0, 0x02014b50, true)
    voce.setUint16(4, 20, true)
    voce.setUint16(6, 20, true)
    voce.setUint16(10, 0, true)
    voce.setUint32(16, crc, true)
    voce.setUint32(20, dati.length, true)
    voce.setUint32(24, dati.length, true)
    voce.setUint16(28, nomeBytes.length, true)
    voce.setUint32(42, offset, true)
    centrale.push(new Uint8Array(voce.buffer), nomeBytes)

    offset += 30 + nomeBytes.length + dati.length
  }

  const dimensioneCentrale = centrale.reduce((s, p) => s + p.length, 0)
  const fine = new DataView(new ArrayBuffer(22))
  fine.setUint32(0, 0x06054b50, true)
  fine.setUint16(8, voci.length, true)
  fine.setUint16(10, voci.length, true)
  fine.setUint32(12, dimensioneCentrale, true)
  fine.setUint32(16, offset, true)

  return new Blob([...pezzi, ...centrale, new Uint8Array(fine.buffer)], {
    type: 'application/zip',
  })
}
