import { describe, expect, it } from 'vitest'
import { preparaFile, preparaFiles } from './file.js'

const jpeg = () => new File([new Uint8Array([1, 2, 3])], 'foto.jpg', { type: 'image/jpeg' })

describe('preparazione dei file', () => {
  it('rilegge i byte invece di tenere il riferimento al file su disco', async () => {
    const originale = jpeg()
    const pronto = await preparaFile(originale)
    expect(pronto).not.toBe(originale)
    expect(await pronto.arrayBuffer()).toEqual(await originale.arrayBuffer())
  })

  it('deduce il tipo dall estensione quando il file non lo dichiara', async () => {
    // caso tipico delle immagini esportate dalla libreria Foto
    const senzaTipo = new File([new Uint8Array([1])], 'IMG_1234.HEIC', { type: '' })
    expect((await preparaFile(senzaTipo)).type).toBe('image/heic')
  })

  it('scarta il file vuoto, che troncherebbe la richiesta', async () => {
    const vuoto = new File([], 'IMG_9999.HEIC', { type: '' })
    await expect(preparaFile(vuoto)).rejects.toThrow(/vuoto o non più disponibile/)
  })

  it('scarta il file oltre il limite, citandone il nome', async () => {
    await expect(preparaFile(jpeg(), { maxBytes: 2 })).rejects.toThrow(/foto\.jpg: troppo grande/)
  })

  it('spiega cosa fare se il file non e leggibile', async () => {
    const irraggiungibile = {
      name: 'IMG_1.HEIC', size: 10, type: '',
      arrayBuffer: () => Promise.reject(new DOMException('not readable', 'NotReadableError')),
    }
    await expect(preparaFile(irraggiungibile)).rejects.toThrow(/app Foto/)
  })

  it('in blocco tiene i file buoni e segnala solo quelli scartati', async () => {
    const { pronti, problemi } = await preparaFiles([
      jpeg(),
      new File([], 'rotta.heic', { type: '' }),
      jpeg(),
    ])
    expect(pronti).toHaveLength(2)
    expect(problemi).toEqual([expect.stringContaining('rotta.heic')])
  })
})
