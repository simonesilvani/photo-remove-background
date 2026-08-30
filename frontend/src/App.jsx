import { useEffect, useRef, useState } from 'react'
import Dropzone from './components/Dropzone.jsx'
import CompareSlider from './components/CompareSlider.jsx'
import Controls, { PRESETS } from './components/Controls.jsx'
import { fetchLimits, fetchModels, removeBackground } from './api.js'
import { copiaImmagine, supportaCopia } from './clipboard.js'
import { preparaFile, preparaFiles } from './file.js'
import { creaZip } from './zip.js'

// Valore di ripiego: quello vero arriva da /api/health all'avvio.
const MAX_BYTES_DEFAULT = 15 * 1024 * 1024

export default function App() {
  const [models, setModels] = useState([])
  const [model, setModel] = useState('u2net')
  const [alphaMatting, setAlphaMatting] = useState(false)
  const [formato, setFormato] = useState('png')
  const [trim, setTrim] = useState(false)
  const [maxBytes, setMaxBytes] = useState(MAX_BYTES_DEFAULT)
  const [copiato, setCopiato] = useState(false)
  const [blocco, setBlocco] = useState([])
  const [anteprima, setAnteprima] = useState(null)
  const [risultatiBlocco, setRisultatiBlocco] = useState(new Map())
  const [progresso, setProgresso] = useState(null)
  const [scarti, setScarti] = useState(new Map())
  const maxBytesRef = useRef(MAX_BYTES_DEFAULT)
  const [bgPreset, setBgPreset] = useState('transparent')
  const [customColor, setCustomColor] = useState('#4f46e5')

  const [file, setFile] = useState(null)
  const [originalUrl, setOriginalUrl] = useState(null)
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const abortRef = useRef(null)

  useEffect(() => {
    fetchModels()
      .then((data) => {
        setModels(data.models)
        setModel(data.default)
      })
      .catch(() => setError('Backend non raggiungibile: avvia il server su localhost:8000'))
    fetchLimits()
      .then((l) => {
        if (!l?.max_upload_bytes) return
        setMaxBytes(l.max_upload_bytes)
        maxBytesRef.current = l.max_upload_bytes // il gestore di ⌘V legge da qui
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    const onPaste = (e) => {
      const item = [...(e.clipboardData?.items ?? [])].find((i) => i.type.startsWith('image/'))
      if (item) selectFile(item.getAsFile())
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  }, [])

  /** Mostra o nasconde l'anteprima di un file del blocco.
   *
   * L'object URL viene creato solo all'apertura e revocato subito dopo: con
   * dieci foto da qualche MB, tenerle tutte decodificate costerebbe memoria
   * per immagini che l'utente magari non guarda nemmeno.
   */
  function alternaAnteprima(chiave, file, riga) {
    setAnteprima((prev) => {
      if (prev) URL.revokeObjectURL(prev.url)
      if (prev?.chiave === chiave) return null
      // Porta la riga in vista: aprendo l'anteprima di un file in fondo, senza
      // questo si aprirebbe fuori dallo schermo.
      requestAnimationFrame(() => riga?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }))
      return { chiave, url: URL.createObjectURL(file) }
    })
  }

  function scartaRisultatiBlocco() {
    setRisultatiBlocco((prev) => {
      for (const url of prev.values()) URL.revokeObjectURL(url)
      return new Map()
    })
  }

  function chiudiAnteprima() {
    setAnteprima((prev) => {
      if (prev) URL.revokeObjectURL(prev.url)
      return null
    })
  }

  async function selectFiles(lista) {
    const files = [...lista]
    if (files.length === 1) {
      setBlocco([])
      return selectFile(files[0])
    }

    chiudiAnteprima()
    scartaRisultatiBlocco()
    setScarti(new Map())
    setProgresso(null)
    const { pronti, problemi } = await preparaFiles(files, { maxBytes: maxBytesRef.current })
    if (!pronti.length) {
      setError(problemi.join(' · ') || 'Nessuna immagine utilizzabile')
      return
    }
    setError(problemi.length ? `${problemi.length} scartate — ${problemi.join(' · ')}` : null)
    setResult(null)
    // Identita' propria per ogni file: due foto possono chiamarsi allo stesso
    // modo (capita prendendole da cartelle diverse) e il nome non basta a
    // distinguerle, ne' come chiave di React ne' per ritrovarne il risultato.
    setBlocco(pronti.map((file) => ({ id: crypto.randomUUID(), file })))
    setFile(null)
    setOriginalUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev)
      return null
    })
  }

  async function selectFile(next) {
    if (!next) return
    let copia
    try {
      copia = await preparaFile(next, { maxBytes: maxBytesRef.current })
    } catch (err) {
      setError(err.message)
      return
    }
    setError(null)
    setResult(null)
    setFile(copia)
    setOriginalUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev)
      return URL.createObjectURL(copia)
    })
  }

  /** Nome della voce nello ZIP: estensione nuova e nessuna collisione. */
  function nomeVoceZip(nome, estensione, usati) {
    const base = nome.split('/').pop().replace(/\.[^.]+$/, '') || 'immagine'
    let candidato = `${base}.${estensione}`
    let contatore = 2
    while (usati.has(candidato)) candidato = `${base}-${contatore++}.${estensione}`
    usati.add(candidato)
    return candidato
  }

  function backgroundValue() {
    if (bgPreset === 'custom') return customColor
    return PRESETS.find((p) => p.id === bgPreset)?.value ?? null
  }

  async function handleSubmit() {
    if ((!file && !blocco.length) || loading) return
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    setError(null)
    try {
      if (blocco.length) {
        // Una alla volta invece dell'endpoint /batch: il server le elabora
        // comunque in sequenza, ma cosi' l'utente vede a che punto siamo e i
        // singoli risultati sono disponibili appena pronti.
        const fatti = new Map()
        const problemi = new Map()
        for (const [i, { id, file }] of blocco.entries()) {
          setProgresso({ fatte: i, totali: blocco.length, nome: file.name })
          try {
            const esito = await removeBackground({
              file,
              model,
              alphaMatting,
              background: backgroundValue(),
              formato,
              trim,
              signal: controller.signal,
            })
            fatti.set(id, esito)
          } catch (err) {
            if (err.name === 'AbortError') return
            problemi.set(id, `${file.name}: ${err.message}`)
          }
        }
        setProgresso(null)
        setScarti(problemi)
        if (!fatti.size) {
          setError([...problemi.values()].join(' · ') || 'Nessuna immagine elaborata')
          return
        }

        const usati = new Set()
        const nomePerId = new Map(blocco.map(({ id, file }) => [id, file.name]))
        const voci = [...fatti].map(([id, esito]) => ({
          nome: nomeVoceZip(nomePerId.get(id), formato, usati),
          blob: esito.blob,
        }))
        const zip = await creaZip(voci)
        setResult((prev) => {
          if (prev?.url) URL.revokeObjectURL(prev.url)
          return {
            url: URL.createObjectURL(zip),
            zip: true,
            formato,
            elaborate: fatti.size,
            scartate: problemi.size,
          }
        })
        setRisultatiBlocco((prev) => {
          for (const url of prev.values()) URL.revokeObjectURL(url)
          return new Map([...fatti].map(([id, esito]) => [id, esito.url]))
        })
        return
      }
      const next = await removeBackground({
        file,
        model,
        alphaMatting,
        background: backgroundValue(),
        formato,
        trim,
        signal: controller.signal,
      })
      setResult((prev) => {
        if (prev?.url) URL.revokeObjectURL(prev.url)
        return next
      })
      // Dopo il primo uso i pesi sono in cache: aggiorna gli avvisi di download.
      if (modelloDaScaricare) fetchModels().then((d) => setModels(d.models)).catch(() => {})
    } catch (err) {
      if (err.name !== 'AbortError') setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  function annulla() {
    abortRef.current?.abort()
    setLoading(false)
  }

  async function copia() {
    try {
      await copiaImmagine(result.blob)
      setCopiato(true)
      setTimeout(() => setCopiato(false), 2000)
    } catch (err) {
      setError(err.message)
    }
  }

  function reset() {
    abortRef.current?.abort()
    chiudiAnteprima()
    scartaRisultatiBlocco()
    setScarti(new Map())
    setProgresso(null)
    setBlocco([])
    setFile(null)
    setOriginalUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev)
      return null
    })
    setResult((prev) => {
      if (prev?.url) URL.revokeObjectURL(prev.url)
      return null
    })
    setError(null)
  }

  // Il nome e l'etichetta seguono il formato con cui il risultato e' stato
  // prodotto, non quello selezionato ora: cambiando menu senza rielaborare
  // si scaricherebbe un file con l'estensione sbagliata.
  const formatoRisultato = result?.formato ?? formato
  // Il modello scelto non e' ancora sul disco: la prima richiesta lo scarichera'.
  const modelloDaScaricare = models.find((m) => m.id === model && m.downloaded === false)

  const downloadName = file
    ? `${file.name.replace(/\.[^.]+$/, '')}-no-bg.${formatoRisultato}`
    : `no-bg.${formatoRisultato}`

  return (
    <div className="app">
      <header className="header">
        <h1>Remove Background</h1>
        <p>Carica un'immagine e ottieni il soggetto ritagliato, in PNG o WEBP.</p>
      </header>

      <main className="layout">
        <section className="panel">
          {blocco.length ? (
            <div className="blocco">
              <p className="blocco__titolo">
                {blocco.length} immagini pronte
                {result?.zip && ` · ${result.elaborate} elaborate`}
                {result?.scartate ? `, ${result.scartate} scartate` : ''}
              </p>
              <ul className="blocco__lista">
                {blocco.map(({ id, file }) => {
                  const aperta = anteprima?.chiave === id
                  const risultato = risultatiBlocco.get(id)
                  const scarto = scarti.get(id)
                  return (
                    <li key={id}>
                      <div className="blocco__riga">
                        <span className="filename">{file.name}</span>
                        <span className="badge">{Math.round(file.size / 1024)} KB</span>
                        {risultato && <span className="esito esito--ok" title="Elaborata">✓</span>}
                        {scarto && (
                          <span className="esito esito--ko" title={scarto}>
                            ✕
                          </span>
                        )}
                        <button
                          type="button"
                          className="btn-mini"
                          aria-expanded={aperta}
                          onClick={(e) => alternaAnteprima(id, file, e.currentTarget.closest('li'))}
                        >
                          {aperta ? 'Nascondi' : 'Anteprima'}
                        </button>
                      </div>
                      {aperta &&
                        (risultato ? (
                          <div className="blocco__confronto">
                            <CompareSlider
                              before={anteprima.url}
                              after={risultato}
                              checkerboard={bgPreset === 'transparent'}
                            />
                          </div>
                        ) : (
                          <img
                            className="blocco__anteprima"
                            src={anteprima.url}
                            alt={`Anteprima di ${file.name}`}
                          />
                        ))}
                    </li>
                  )
                })}
              </ul>
              {loading && progresso && (
                <div className="blocco__stato">
                  <div className="barra" role="progressbar" aria-valuenow={progresso.fatte}
                       aria-valuemin={0} aria-valuemax={progresso.totali}>
                    <span style={{ width: `${(progresso.fatte / progresso.totali) * 100}%` }} />
                  </div>
                  <p>
                    <span className="spinner" aria-hidden="true" />
                    {progresso.fatte + 1} di {progresso.totali} · {progresso.nome}
                  </p>
                </div>
              )}
            </div>
          ) : !originalUrl ? (
            <Dropzone onFile={selectFiles} disabled={loading} />
          ) : (
            <div className="preview">
              {result ? (
                <CompareSlider
                  before={originalUrl}
                  after={result.url}
                  checkerboard={bgPreset === 'transparent'}
                />
              ) : (
                <div className="preview__single">
                  <img src={originalUrl} alt="Anteprima dell'immagine caricata" />
                  {loading && (
                    <div className="preview__loading">
                      <span className="spinner" aria-hidden="true" />
                      <span>
                        {modelloDaScaricare
                          ? `Scaricamento del modello (${modelloDaScaricare.size_mb} MB), solo la prima volta…`
                          : 'Elaborazione in corso…'}
                      </span>
                    </div>
                  )}
                </div>
              )}
              <div className="preview__meta">
                <span className="filename" title={file?.name}>{file?.name}</span>
                {result?.elapsed != null && (
                  <span className="badge">
                    {result.width}×{result.height} · {result.elapsed.toFixed(1)}s
                  </span>
                )}
              </div>
            </div>
          )}
        </section>

        <aside className="panel panel--side">
          <Controls
            models={models}
            model={model}
            onModelChange={setModel}
            formato={formato}
            onFormatoChange={setFormato}
            alphaMatting={alphaMatting}
            onAlphaMattingChange={setAlphaMatting}
            trim={trim}
            onTrimChange={setTrim}
            bgPreset={bgPreset}
            onBgPresetChange={setBgPreset}
            customColor={customColor}
            onCustomColorChange={setCustomColor}
            disabled={loading}
          />

          {error && <p className="error" role="alert">{error}</p>}

          <div className="actions">
            {loading ? (
              <button className="btn btn--danger" onClick={annulla}>
                Annulla
              </button>
            ) : (
              <button className="btn btn--primary" onClick={handleSubmit} disabled={!file && !blocco.length}>
                {result ? 'Rielabora' : blocco.length ? `Rimuovi sfondo da ${blocco.length}` : 'Rimuovi sfondo'}
              </button>
            )}
            {result?.zip && (
              <a className="btn btn--ghost" href={result.url} download="senza-sfondo.zip">
                Scarica ZIP ({result.elaborate})
              </a>
            )}
            {result && !result.zip && (
              <a className="btn btn--ghost" href={result.url} download={downloadName}>
                Scarica {formatoRisultato.toUpperCase()}
              </a>
            )}
            {result && !result.zip && supportaCopia() && (
              <button className="btn btn--ghost" onClick={copia} disabled={loading}>
                {copiato ? 'Copiato ✓' : 'Copia negli appunti'}
              </button>
            )}
            {(file || blocco.length > 0) && (
              <button className="btn btn--ghost" onClick={reset} disabled={loading}>
                Nuova immagine
              </button>
            )}
          </div>
        </aside>
      </main>
    </div>
  )
}
