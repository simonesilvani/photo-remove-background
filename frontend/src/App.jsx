import { useEffect, useRef, useState } from 'react'
import Dropzone from './components/Dropzone.jsx'
import CompareSlider from './components/CompareSlider.jsx'
import Controls, { PRESETS } from './components/Controls.jsx'
import { fetchLimits, fetchModels, removeBackground } from './api.js'

// Valore di ripiego: quello vero arriva da /api/health all'avvio.
const MAX_BYTES_DEFAULT = 15 * 1024 * 1024

export default function App() {
  const [models, setModels] = useState([])
  const [model, setModel] = useState('u2net')
  const [alphaMatting, setAlphaMatting] = useState(false)
  const [formato, setFormato] = useState('png')
  const [maxBytes, setMaxBytes] = useState(MAX_BYTES_DEFAULT)
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

  // Estensione -> tipo MIME, per i file che arrivano senza `type` valorizzato.
  const TIPI = {
    jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png',
    webp: 'image/webp', bmp: 'image/bmp', tif: 'image/tiff', tiff: 'image/tiff',
  }

  async function selectFile(next) {
    if (!next) return
    const limite = maxBytesRef.current
    if (next.size > limite) {
      setError(`Immagine troppo grande: il limite e’ ${Math.round(limite / 1024 / 1024)} MB`)
      return
    }

    // I byte si leggono subito, non all'invio: le immagini della libreria Foto sono
    // file temporanei che possono sparire, e la richiesta partirebbe senza allegato.
    let bytes
    try {
      bytes = await next.arrayBuffer()
    } catch {
      setError(
        'Impossibile leggere il file. Se viene dall’app Foto, esportalo prima sul disco e riprova.'
      )
      return
    }
    if (!bytes.byteLength) {
      setError('Il file selezionato è vuoto o non più disponibile.')
      return
    }

    const estensione = next.name?.split('.').pop()?.toLowerCase() ?? ''
    const tipo = next.type || TIPI[estensione] || 'application/octet-stream'
    const copia = new File([bytes], next.name || 'immagine', { type: tipo })

    setError(null)
    setResult(null)
    setFile(copia)
    setOriginalUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev)
      return URL.createObjectURL(copia)
    })
  }

  function backgroundValue() {
    if (bgPreset === 'custom') return customColor
    return PRESETS.find((p) => p.id === bgPreset)?.value ?? null
  }

  async function handleSubmit() {
    if (!file || loading) return
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    setError(null)
    try {
      const next = await removeBackground({
        file,
        model,
        alphaMatting,
        background: backgroundValue(),
        formato,
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

  function reset() {
    abortRef.current?.abort()
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
          {!originalUrl ? (
            <Dropzone onFile={selectFile} disabled={loading} />
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
            bgPreset={bgPreset}
            onBgPresetChange={setBgPreset}
            customColor={customColor}
            onCustomColorChange={setCustomColor}
            disabled={loading}
          />

          {error && <p className="error" role="alert">{error}</p>}

          <div className="actions">
            <button
              className="btn btn--primary"
              onClick={handleSubmit}
              disabled={!file || loading}
            >
              {loading ? 'Elaborazione…' : result ? 'Rielabora' : 'Rimuovi sfondo'}
            </button>
            {result && (
              <a className="btn btn--ghost" href={result.url} download={downloadName}>
                Scarica {formatoRisultato.toUpperCase()}
              </a>
            )}
            {file && (
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
