import { describe, expect, it } from 'vitest'
import { leggiZip } from './zip.js'

// Archivi prodotti dalla stessa libreria che usa il server (zipfile di Python),
// cosi' il lettore viene provato sui byte veri e non su un formato inventato.
const STORED = 'UEsDBBQAAAAAAM1UHV30BvHJRAAAAEQAAAANAAAAbWFuaWZlc3QuanNvbnsicmlzdWx0YXRpIjogW3sib3JpZ2luZSI6ICJhLmpwZyIsICJmaWxlIjogImEucG5nIn1dLCAiZXJyb3JpIjogW119UEsDBBQAAAAAAM1UHV0mTAu3AAQAAAAEAAAFAAAAYS5wbmcAAQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyAhIiMkJSYnKCkqKywtLi8wMTIzNDU2Nzg5Ojs8PT4/QEFCQ0RFRkdISUpLTE1OT1BRUlNUVVZXWFlaW1xdXl9gYWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXp7fH1+f4CBgoOEhYaHiImKi4yNjo+QkZKTlJWWl5iZmpucnZ6foKGio6SlpqeoqaqrrK2ur7CxsrO0tba3uLm6u7y9vr/AwcLDxMXGx8jJysvMzc7P0NHS09TV1tfY2drb3N3e3+Dh4uPk5ebn6Onq6+zt7u/w8fLz9PX29/j5+vv8/f7/AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8gISIjJCUmJygpKissLS4vMDEyMzQ1Njc4OTo7PD0+P0BBQkNERUZHSElKS0xNTk9QUVJTVFVWV1hZWltcXV5fYGFiY2RlZmdoaWprbG1ub3BxcnN0dXZ3eHl6e3x9fn+AgYKDhIWGh4iJiouMjY6PkJGSk5SVlpeYmZqbnJ2en6ChoqOkpaanqKmqq6ytrq+wsbKztLW2t7i5uru8vb6/wMHCw8TFxsfIycrLzM3Oz9DR0tPU1dbX2Nna29zd3t/g4eLj5OXm5+jp6uvs7e7v8PHy8/T19vf4+fr7/P3+/wABAgMEBQYHCAkKCwwNDg8QERITFBUWFxgZGhscHR4fICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj9AQUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVpbXF1eX2BhYmNkZWZnaGlqa2xtbm9wcXJzdHV2d3h5ent8fX5/gIGCg4SFhoeIiYqLjI2Oj5CRkpOUlZaXmJmam5ydnp+goaKjpKWmp6ipqqusra6vsLGys7S1tre4ubq7vL2+v8DBwsPExcbHyMnKy8zNzs/Q0dLT1NXW19jZ2tvc3d7f4OHi4+Tl5ufo6err7O3u7/Dx8vP09fb3+Pn6+/z9/v8AAQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyAhIiMkJSYnKCkqKywtLi8wMTIzNDU2Nzg5Ojs8PT4/QEFCQ0RFRkdISUpLTE1OT1BRUlNUVVZXWFlaW1xdXl9gYWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXp7fH1+f4CBgoOEhYaHiImKi4yNjo+QkZKTlJWWl5iZmpucnZ6foKGio6SlpqeoqaqrrK2ur7CxsrO0tba3uLm6u7y9vr/AwcLDxMXGx8jJysvMzc7P0NHS09TV1tfY2drb3N3e3+Dh4uPk5ebn6Onq6+zt7u/w8fLz9PX29/j5+vv8/f7/UEsBAhQDFAAAAAAAzVQdXfQG8clEAAAARAAAAA0AAAAAAAAAAAAAAIABAAAAAG1hbmlmZXN0Lmpzb25QSwECFAMUAAAAAADNVB1dJkwLtwAEAAAABAAABQAAAAAAAAAAAAAAgAFvAAAAYS5wbmdQSwUGAAAAAAIAAgBuAAAAkgQAAAAA'
const DEFLATED = 'UEsDBBQAAAAIAM1UHV30BvHJOwAAAEQAAAANAAAAbWFuaWZlc3QuanNvbqtWKsosLs0pSSzJVLJSiK5Wyi/KTM/MSwVylBL1sgrSlXQUlNIyc6ACBXnpSrWxQKHUoiKgSpCW2FoAUEsDBBQAAAAIAM1UHV0mTAu3GAEAAAAEAAAFAAAAYS5wbmdjYGRiZmFlY+fg5OLm4eXjFxAUEhYRFROXkJSSlpGVk1dQVFJWUVVT19DU0tbR1dM3MDQyNjE1M7ewtLK2sbWzd3B0cnZxdXP38PTy9vH18w8IDAoOCQ0Lj4iMio6JjYtPSExKTklNS8/IzMrOyc3LLygsKi4pLSuvqKyqrqmtq29obGpuaW1r7+js6u7p7eufMHHS5ClTp02fMXPW7Dlz581fsHDR4iVLly1fsXLV6jVr163fsHHT5i1bt23fsXPX7j179+0/cPDQ4SNHjx0/cfLU6TNnz52/cPHS5StXr12/cfPW7Tt3791/8PDR4ydPnz1/8fLV6zdv373/8PHT5y9fv33/8fPX7z9///1nGPX/qP9HsP8BUEsBAhQDFAAAAAgAzVQdXfQG8ck7AAAARAAAAA0AAAAAAAAAAAAAAIABAAAAAG1hbmlmZXN0Lmpzb25QSwECFAMUAAAACADNVB1dJkwLtxgBAAAABAAABQAAAAAAAAAAAAAAgAFmAAAAYS5wbmdQSwUGAAAAAAIAAgBuAAAAoQEAAAAA'

function blobDaBase64(b64) {
  const binario = atob(b64)
  const byte = Uint8Array.from(binario, (c) => c.charCodeAt(0))
  return new Blob([byte], { type: 'application/zip' })
}

describe('lettura dello ZIP', () => {
  it('estrae le voci di un archivio non compresso', async () => {
    const dentro = await leggiZip(blobDaBase64(STORED))
    expect([...dentro.keys()].sort()).toEqual(['a.png', 'manifest.json'])
    const manifest = JSON.parse(await dentro.get('manifest.json').text())
    expect(manifest.risultati).toEqual([{ origine: 'a.jpg', file: 'a.png' }])
    expect(dentro.get('a.png').size).toBe(1024)
  })

  it('gestisce anche gli archivi compressi', async () => {
    // il server usa ZIP_STORED, ma cambiando compressione l'interfaccia regge
    const dentro = await leggiZip(blobDaBase64(DEFLATED))
    expect(dentro.get('a.png').size).toBe(1024)
  })

  it('assegna il tipo MIME in base all estensione', async () => {
    const dentro = await leggiZip(blobDaBase64(STORED), { png: 'image/png' })
    expect(dentro.get('a.png').type).toBe('image/png')
  })

  it('rifiuta un file che non e uno ZIP', async () => {
    await expect(leggiZip(new Blob(['non sono un archivio']))).rejects.toThrow(/non valido/)
  })
})
