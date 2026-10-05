import { useCallback, useEffect, useRef, useState } from 'react'

export interface GeoFix {
  latitude: number
  longitude: number
  accuracy: number | null
  timestamp: number
}

type Status = 'idle' | 'locating' | 'granted' | 'denied' | 'unsupported' | 'error'

/**
 * Geolocation hook used to auto-fill the "my location" fields in the report
 * modal and the route planner. Never blocks the UI: the demo works fully with
 * map-click picking even if the browser refuses the permission prompt.
 */
export function useGeolocation() {
  const [fix, setFix] = useState<GeoFix | null>(null)
  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState<string | null>(null)
  const watchId = useRef<number | null>(null)

  const locate = useCallback(() => {
    if (!('geolocation' in navigator)) {
      setStatus('unsupported')
      setError('This browser does not expose the Geolocation API.')
      return
    }
    setStatus('locating')
    setError(null)
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setFix({
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
          accuracy: position.coords.accuracy,
          timestamp: position.timestamp,
        })
        setStatus('granted')
      },
      (positionError) => {
        setStatus(positionError.code === positionError.PERMISSION_DENIED ? 'denied' : 'error')
        setError(positionError.message)
      },
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 30_000 },
    )
  }, [])

  useEffect(
    () => () => {
      if (watchId.current !== null) navigator.geolocation.clearWatch(watchId.current)
    },
    [],
  )

  return { fix, status, error, locate, isLocating: status === 'locating' }
}
