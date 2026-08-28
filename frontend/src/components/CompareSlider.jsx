import { useCallback, useEffect, useRef, useState } from 'react'

// Spazio minimo (px) perche' un'etichetta stia dentro la propria meta'.
const LARGHEZZA_ETICHETTA = 120

/** Confronto originale/risultato con maniglia trascinabile. */
export default function CompareSlider({ before, after, checkerboard = true }) {
  const containerRef = useRef(null)
  const [position, setPosition] = useState(50)
  const [width, setWidth] = useState(0)
  const draggingRef = useRef(false)

  // L'immagine "prima" sta dentro un contenitore ritagliato: per non deformarla
  // deve restare larga quanto l'intero riquadro, quindi ne misuriamo la larghezza.
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    observer.observe(el)
    setWidth(el.clientWidth)
    return () => observer.disconnect()
  }, [])

  const updateFromClientX = useCallback((clientX) => {
    const el = containerRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const pct = ((clientX - rect.left) / rect.width) * 100
    setPosition(Math.min(100, Math.max(0, pct)))
  }, [])

  useEffect(() => {
    const onMove = (e) => {
      if (!draggingRef.current) return
      updateFromClientX(e.touches ? e.touches[0].clientX : e.clientX)
    }
    const onUp = () => {
      draggingRef.current = false
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    window.addEventListener('touchmove', onMove, { passive: true })
    window.addEventListener('touchend', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      window.removeEventListener('touchmove', onMove)
      window.removeEventListener('touchend', onUp)
    }
  }, [updateFromClientX])

  // Ogni etichetta sparisce quando la sua meta' si stringe troppo per contenerla:
  // altrimenti "Originale" resterebbe scritto sopra il risultato senza sfondo.
  const sinistraPx = (width * position) / 100
  const destraPx = width - sinistraPx
  const etichetta = (spazio) => ({
    opacity: width && spazio < LARGHEZZA_ETICHETTA ? 0 : 1,
  })

  return (
    <div
      className={`compare ${checkerboard ? 'compare--checker' : ''}`}
      ref={containerRef}
      onMouseDown={(e) => {
        draggingRef.current = true
        updateFromClientX(e.clientX)
      }}
      onTouchStart={(e) => {
        draggingRef.current = true
        updateFromClientX(e.touches[0].clientX)
      }}
    >
      <img className="compare__img" src={after} alt="Risultato senza sfondo" />
      <div className="compare__overlay" style={{ width: `${position}%` }}>
        <img
          className="compare__img"
          src={before}
          alt="Immagine originale"
          style={{ width: width ? `${width}px` : '100%', maxWidth: 'none' }}
        />
      </div>
      <div
        className="compare__handle"
        style={{ left: `${position}%` }}
        role="slider"
        aria-label="Confronto prima/dopo"
        aria-valuenow={Math.round(position)}
        aria-valuemin={0}
        aria-valuemax={100}
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'ArrowLeft') setPosition((p) => Math.max(0, p - 5))
          if (e.key === 'ArrowRight') setPosition((p) => Math.min(100, p + 5))
        }}
      >
        <span className="compare__grip" aria-hidden="true">↔</span>
      </div>
      <span className="compare__label compare__label--left" style={etichetta(sinistraPx)}>
        Originale
      </span>
      <span className="compare__label compare__label--right" style={etichetta(destraPx)}>
        Senza sfondo
      </span>
    </div>
  )
}
