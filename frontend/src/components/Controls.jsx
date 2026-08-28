const PRESETS = [
  { id: 'transparent', label: 'Trasparente', value: null, swatch: 'transparent' },
  { id: 'white', label: 'Bianco', value: '#ffffff', swatch: '#ffffff' },
  { id: 'black', label: 'Nero', value: '#111111', swatch: '#111111' },
  { id: 'custom', label: 'Personalizzato', value: null, swatch: null },
]

export default function Controls({
  models,
  model,
  onModelChange,
  alphaMatting,
  onAlphaMattingChange,
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
            </option>
          ))}
        </select>
        {current && <span className="field__hint">{current.description}</span>}
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
          checked={alphaMatting}
          disabled={disabled}
          onChange={(e) => onAlphaMattingChange(e.target.checked)}
        />
        <span>
          <span className="field__label">Alpha matting</span>
          <span className="field__hint">Bordi piu' morbidi (capelli, pelo) — piu' lento</span>
        </span>
      </label>
    </div>
  )
}

export { PRESETS }
