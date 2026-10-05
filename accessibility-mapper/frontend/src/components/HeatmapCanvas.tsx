import { useEffect, useRef } from 'react'
import L from 'leaflet'
import { useMap } from 'react-leaflet'
import type { HeatPoint } from '@/types'

interface HeatmapCanvasProps {
  points: HeatPoint[]
  /** Base radius in pixels at zoom 16; scales with zoom. */
  radius?: number
  onBlur?: (intensity: number) => void
}

/**
 * Radial-gradient heat layer rendered on a canvas overlay.
 *
 * Hand-rolled instead of pulling in `leaflet.heat` (3 KB) because the additive
 * blend needs to weight *severity*, not just report count - a broken lift is
 * not the same as a missing sign. No extra dependency, full control.
 */
export function HeatmapCanvas({ points, radius = 46 }: HeatmapCanvasProps) {
  const map = useMap()
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    if (!map) return
    const canvas = L.DomUtil.create('canvas', 'abm-heat-canvas') as HTMLCanvasElement
    canvas.style.position = 'absolute'
    canvas.style.pointerEvents = 'none'
    canvas.style.opacity = '0.82'
    canvas.style.mixBlendMode = 'multiply'
    map.getPanes().overlayPane.appendChild(canvas)
    canvasRef.current = canvas

    const maxIntensity = Math.max(1, ...points.map((point) => point.intensity))

    const draw = () => {
      const size = map.getSize()
      const dpr = window.devicePixelRatio || 1
      canvas.width = size.x * dpr
      canvas.height = size.y * dpr
      canvas.style.width = `${size.x}px`
      canvas.style.height = `${size.y}px`
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, size.x, size.y)
      L.DomUtil.setPosition(canvas, map.containerPointToLayerPoint([0, 0]))

      const zoom = map.getZoom()
      const scaledRadius = radius * Math.pow(2, Math.max(-2, zoom - 16) * 0.6)

      for (const point of points) {
        const layerPoint = map.latLngToLayerPoint([point.latitude, point.longitude])
        const containerPoint = map.layerPointToContainerPoint(layerPoint)
        if (
          containerPoint.x < -scaledRadius ||
          containerPoint.y < -scaledRadius ||
          containerPoint.x > size.x + scaledRadius ||
          containerPoint.y > size.y + scaledRadius
        ) {
          continue
        }
        const normalized = Math.min(1, point.intensity / maxIntensity)
        const r = scaledRadius * (0.55 + 0.45 * normalized)
        const gradient = ctx.createRadialGradient(
          containerPoint.x,
          containerPoint.y,
          0,
          containerPoint.x,
          containerPoint.y,
          r,
        )
        const alpha = 0.28 + 0.5 * normalized
        gradient.addColorStop(0, `rgba(220, 38, 38, ${alpha})`)
        gradient.addColorStop(0.45, `rgba(234, 88, 12, ${alpha * 0.75})`)
        gradient.addColorStop(0.8, `rgba(245, 158, 11, ${alpha * 0.35})`)
        gradient.addColorStop(1, 'rgba(245, 158, 11, 0)')
        ctx.fillStyle = gradient
        ctx.beginPath()
        ctx.arc(containerPoint.x, containerPoint.y, r, 0, Math.PI * 2)
        ctx.fill()
      }
    }

    draw()
    map.on('move zoom viewreset resize', draw)
    return () => {
      map.off('move zoom viewreset resize', draw)
      L.DomUtil.remove(canvas)
      canvasRef.current = null
    }
  }, [map, points, radius])

  return null
}
