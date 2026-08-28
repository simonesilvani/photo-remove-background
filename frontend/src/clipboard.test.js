import { afterEach, describe, expect, it, vi } from 'vitest'
import { copiaImmagine, supportaCopia } from './clipboard.js'

const png = new Blob([new Uint8Array([1])], { type: 'image/png' })
const webp = new Blob([new Uint8Array([2])], { type: 'image/webp' })

function appuntiFinti() {
  const scritti = []
  vi.stubGlobal('ClipboardItem', class { constructor(dati) { this.dati = dati } })
  vi.stubGlobal('navigator', { clipboard: { write: async (items) => scritti.push(...items) } })
  return scritti
}

afterEach(() => vi.unstubAllGlobals())

describe('copia negli appunti', () => {
  it('segnala i browser che non la permettono', () => {
    vi.stubGlobal('ClipboardItem', undefined)
    vi.stubGlobal('navigator', {})
    expect(supportaCopia()).toBe(false)
  })

  it('rifiuta con un messaggio comprensibile se non supportata', async () => {
    vi.stubGlobal('ClipboardItem', undefined)
    vi.stubGlobal('navigator', {})
    await expect(copiaImmagine(png)).rejects.toThrow(/non permette/)
  })

  it('copia un PNG senza riconvertirlo', async () => {
    const scritti = appuntiFinti()
    const converti = vi.fn()
    await copiaImmagine(png, { converti })
    expect(converti).not.toHaveBeenCalled()
    expect(Object.keys(scritti[0].dati)).toEqual(['image/png'])
    await expect(scritti[0].dati['image/png']).resolves.toBe(png)
  })

  it('converte il WEBP, che gli appunti non accettano', async () => {
    const scritti = appuntiFinti()
    const converti = vi.fn(async () => png)
    await copiaImmagine(webp, { converti })
    expect(converti).toHaveBeenCalledWith(webp)
    await expect(scritti[0].dati['image/png']).resolves.toBe(png)
  })

  it('traduce il blocco del browser in un messaggio comprensibile', async () => {
    vi.stubGlobal('ClipboardItem', class {})
    vi.stubGlobal('navigator', {
      clipboard: {
        write: async () => {
          throw Object.assign(new Error("Document is not focused."), { name: 'NotAllowedError' })
        },
      },
    })
    await expect(copiaImmagine(png)).rejects.toThrow(/clicca sulla pagina/)
  })

  it('passa una promessa al ClipboardItem, senza await prima della write', async () => {
    // Safari annulla la scrittura se fra il clic e la write c'e' un await
    const scritti = appuntiFinti()
    await copiaImmagine(webp, { converti: async () => png })
    expect(typeof scritti[0].dati['image/png'].then).toBe('function')
  })
})
