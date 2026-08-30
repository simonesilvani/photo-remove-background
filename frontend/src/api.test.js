import { describe, expect, it, vi } from 'vitest'
import { removeBackground } from './api.js'

const file = new File([new Uint8Array([1, 2, 3])], 'foto.jpg', { type: 'image/jpeg' })
const base = { file, model: 'u2net', bordi: 'hard', formato: 'png' }

function rispostaFinta({ ok = true, status = 200, corpo = null, tipo = 'image/png' } = {}) {
  return {
    ok,
    status,
    statusText: '',
    headers: { get: (k) => (k.toLowerCase() === 'content-type' ? tipo : null) },
    json: async () => {
      if (corpo === null) throw new SyntaxError('non e\' JSON')
      return corpo
    },
    blob: async () => new Blob([new Uint8Array([1])], { type: 'image/png' }),
  }
}

describe('removeBackground', () => {
  it('abbandona la richiesta quando il server non risponde', async () => {
    // fetch che non risolve mai: senza timeout il chiamante resterebbe appeso
    vi.stubGlobal('fetch', (_url, opzioni) =>
      new Promise((_, reject) => {
        opzioni.signal.addEventListener('abort', () =>
          reject(Object.assign(new Error('aborted'), { name: 'AbortError' }))
        )
      })
    )
    await expect(removeBackground({ ...base, timeoutMs: 30 })).rejects.toThrow(
      /non ha risposto in tempo/
    )
  })

  it('propaga l annullamento manuale come AbortError', async () => {
    const controller = new AbortController()
    vi.stubGlobal('fetch', (_url, opzioni) =>
      new Promise((_, reject) => {
        opzioni.signal.addEventListener('abort', () =>
          reject(Object.assign(new Error('aborted'), { name: 'AbortError' }))
        )
      })
    )
    const promessa = removeBackground({ ...base, signal: controller.signal })
    controller.abort()
    await expect(promessa).rejects.toHaveProperty('name', 'AbortError')
  })

  it('usa il messaggio del server quando detail e una stringa', async () => {
    vi.stubGlobal('fetch', async () =>
      rispostaFinta({ ok: false, status: 415, corpo: { detail: 'Tipo non supportato: image/heic' }, tipo: 'application/json' })
    )
    await expect(removeBackground(base)).rejects.toThrow('Tipo non supportato: image/heic')
  })

  it('rende leggibili gli errori di validazione, che sono una lista di oggetti', async () => {
    // regressione: prima l'interfaccia mostrava "[object Object]"
    vi.stubGlobal('fetch', async () =>
      rispostaFinta({
        ok: false, status: 422, tipo: 'application/json',
        corpo: { detail: [{ loc: ['body', 'file'], msg: 'Field required' }] },
      })
    )
    await expect(removeBackground(base)).rejects.toThrow('file: Field required')
  })

  it('non mostra [object Object] con una risposta non JSON', async () => {
    vi.stubGlobal('fetch', async () => rispostaFinta({ ok: false, status: 502, tipo: 'text/html' }))
    await expect(removeBackground(base)).rejects.toThrow(/502/)
  })

  it('restituisce il formato usato, per non sbagliare estensione al download', async () => {
    vi.stubGlobal('fetch', async () => rispostaFinta())
    vi.stubGlobal('URL', { ...URL, createObjectURL: () => 'blob:finto' })
    const esito = await removeBackground({ ...base, formato: 'webp' })
    expect(esito.formato).toBe('webp')
  })
})
