import { useCallback, useEffect, useState } from 'react'
import {
  apiError,
  fetchActiveBarriers,
  fetchCategories,
  fetchNetwork,
  fetchOverview,
  fetchPresets,
} from '@/services/api'
import type {
  BarrierCollection,
  Bounds,
  CategoryInfo,
  NetworkCollection,
  Overview,
  Preset,
} from '@/types'

interface CampusData {
  overview: Overview | null
  barriers: BarrierCollection | null
  network: NetworkCollection | null
  presets: Preset[]
  categories: CategoryInfo[]
  bounds: Bounds | null
  error: string | null
  loading: boolean
  lastUpdated: Date | null
  refresh: () => void
}

/**
 * Loads the boot payload plus the two live GeoJSON layers the map renders.
 * A modest poll keeps the dashboard honest during a demo without hammering
 * the API; `refresh()` is called after every mutation for instant feedback.
 */
export function useCampusData(pollMs = 15_000): CampusData {
  const [overview, setOverview] = useState<Overview | null>(null)
  const [barriers, setBarriers] = useState<BarrierCollection | null>(null)
  const [network, setNetwork] = useState<NetworkCollection | null>(null)
  const [presets, setPresets] = useState<Preset[]>([])
  const [categories, setCategories] = useState<CategoryInfo[]>([])
  const [bounds, setBounds] = useState<Bounds | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [tick, setTick] = useState(0)

  const refresh = useCallback(() => setTick((value) => value + 1), [])

  useEffect(() => {
    let cancelled = false

    async function loadStatic() {
      setLoading(true)
      try {
        const [overviewData, networkData, presetData] = await Promise.all([
          fetchOverview(),
          fetchNetwork(),
          fetchPresets(),
        ])
        if (cancelled) return
        setOverview(overviewData)
        setNetwork(networkData)
        setPresets(presetData.presets)
        setBounds(presetData.bounds)
      } catch (loadError) {
        if (!cancelled) setError(apiError(loadError))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    async function loadLive() {
      try {
        const [barrierData, categoryData] = await Promise.all([fetchActiveBarriers(), fetchCategories()])
        if (cancelled) return
        setBarriers(barrierData)
        setCategories(categoryData.categories)
        setLastUpdated(new Date())
        setError(null)
      } catch (liveError) {
        if (!cancelled) setError(apiError(liveError))
      }
    }

    void loadStatic()
    void loadLive()
    const timer = window.setInterval(loadLive, pollMs)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [pollMs, tick])

  return {
    overview,
    barriers,
    network,
    presets,
    categories,
    bounds,
    error,
    loading,
    lastUpdated,
    refresh,
  }
}
