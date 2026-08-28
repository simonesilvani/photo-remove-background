import { useCallback, useRef, useState } from 'react'

const ACCEPT = 'image/png,image/jpeg,image/webp,image/bmp,image/tiff'

export default function Dropzone({ onFile, disabled }) {
  const inputRef = useRef(null)
  const [dragging, setDragging] = useState(false)

  const handleFiles = useCallback(
    (files) => {
      const file = files?.[0]
      if (file) onFile(file)
    },
    [onFile]
  )

  return (
    <div
      className={`dropzone ${dragging ? 'dropzone--active' : ''} ${disabled ? 'dropzone--disabled' : ''}`}
      onClick={() => !disabled && inputRef.current?.click()}
      onDragOver={(e) => {
        e.preventDefault()
        if (!disabled) setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        if (!disabled) handleFiles(e.dataTransfer.files)
      }}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click()
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        hidden
        onChange={(e) => {
          handleFiles(e.target.files)
          e.target.value = '' // permette di ricaricare lo stesso file
        }}
      />
      <div className="dropzone__icon" aria-hidden="true">🖼️</div>
      <p className="dropzone__title">Trascina qui un'immagine</p>
      <p className="dropzone__hint">
        oppure clicca per sceglierla — puoi anche incollarla con ⌘V
      </p>
      <p className="dropzone__formats">PNG · JPEG · WEBP · BMP · TIFF — max 15 MB</p>
    </div>
  )
}
