const PRESETS = [
  { id: 'transparent', label: 'Trasparente', value: null, swatch: 'transparent' },
  { id: 'white', label: 'Bianco', value: '#ffffff', swatch: '#ffffff' },
  { id: 'black', label: 'Nero', value: '#111111', swatch: '#111111' },
  { id: 'custom', label: 'Personalizzato', value: null, swatch: null },
]

const BORDI = [
  { id: 'hard', label: 'Netti', hint: 'i più rapidi, contorni squadrati' },
  { id: 'soft', label: 'Morbidi', hint: 'sfumati e senza alone del vecchio sfondo' },
  { id: 'max', label: 'Massima qualità', hint: 'meglio su capelli e pelo, più lento' },
]

const FORMATI = [
  { id: 'png', label: 'PNG', hint: 'senza perdita, compatibile ovunque' },
  { id: 'webp', label: 'WEBP', hint: 'stessa resa, file fino a 50 volte piu\u2019 leggero' },
]

export default function Controls({
  models,
  model,
  onModelChange,
  formato,
  onFormatoChange,
  bordi,
  onBordiChange,
  trim,
  onTrimChange,
  bgPreset,
  onBgPresetChange,
  customColor,
  onCustomColorChange,
  disabled,
}) {
  const current = models.find((m) => m.id === model)

  return (
    <div className="controls">
      <label className="field">
        <span className="field__label">Modello</span>
        <select
          value={model}
          disabled={disabled || models.length === 0}
          onChange={(e) => onModelChange(e.target.value)}
        >
          {models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.id}
              {m.downloaded === false ? ` (${m.size_mb} MB da scaricare)` : ''}
            </option>
          ))}
        </select>
        {current && (
          <span className="field__hint">
            {current.description}
            {current.downloaded === false && (
              <>
                {' '}
                <b>· primo utilizzo: {current.size_mb} MB da scaricare</b>
              </>
            )}
          </span>
        )}
      </label>

      <label className="field">
        <span className="field__label">Formato</span>
        <select value={formato} disabled={disabled} onChange={(e) => onFormatoChange(e.target.value)}>
          {FORMATI.map((f) => (
            <option key={f.id} value={f.id}>
              {f.label}
            </option>
          ))}
        </select>
        <span className="field__hint">{FORMATI.find((f) => f.id === formato)?.hint}</span>
      </label>

      <div className="field">
        <span className="field__label">Sfondo</span>
        <div className="swatches">
          {PRESETS.map((p) => (
            <button
              key={p.id}
              type="button"
              disabled={disabled}
              className={`swatch ${bgPreset === p.id ? 'swatch--selected' : ''} ${
                p.id === 'transparent' ? 'swatch--checker' : ''
              }`}
              style={p.swatch && p.swatch !== 'transparent' ? { background: p.swatch } : undefined}
              onClick={() => onBgPresetChange(p.id)}
              title={p.label}
              aria-label={p.label}
            >
              {p.id === 'custom' && (
                <span className="swatch__custom" style={{ background: customColor }} />
              )}
            </button>
          ))}
          {bgPreset === 'custom' && (
            <input
              type="color"
              className="colorpicker"
              value={customColor}
              disabled={disabled}
              onChange={(e) => onCustomColorChange(e.target.value)}
            />
          )}
        </div>
      </div>

      <label className="field field--inline">
        <input
          type="checkbox"
          checked={trim}
          disabled={disabled}
          onChange={(e) => onTrimChange(e.target.checked)}
        />
        <span>
          <span className="field__label">Ritaglia ai bordi</span>
          <span className="field__hint">Elimina i margini trasparenti attorno al soggetto</span>
        </span>
      </label>

      <label className="field">
        <span className="field__label">Bordi</span>
        <select value={bordi} disabled={disabled} onChange={(e) => onBordiChange(e.target.value)}>
          {BORDI.map((b) => (
            <option key={b.id} value={b.id}>
              {b.label}
            </option>
          ))}
        </select>
        <span className="field__hint">{BORDI.find((b) => b.id === bordi)?.hint}</span>
      </label>

      <label className="field field--inline">
        <input
          type="checkbox"
          checked={trim}
          disabled={disabled}
          onChange={(e) => onTrimChange(e.target.checked)}
        />
        <span>
          <span className="field__label">Ritaglia ai bordi</span>
          <span className="field__hint">Elimina i margini trasparenti attorno al soggetto</span>
        </span>
      </label>

    </div>
  )
}

export { PRESETS }
