import { create } from 'zustand'
import type { KnobPosition, KnobValue, ObservationBundle } from '../types'

type MicroworldState = {
  position: KnobPosition
  cache: Map<string, ObservationBundle>
  replacePosition: (position: KnobPosition) => void
  setKnob: (id: string, value: KnobValue) => void
  replaceCache: (cache: Map<string, ObservationBundle>) => void
  putCachedObservation: (key: string, observations: ObservationBundle) => void
}

/** The interaction state: one shared current position and its measured cache. */
export const useMicroworldStore = create<MicroworldState>((set) => ({
  position: {},
  cache: new Map(),
  replacePosition: (position) => set({ position: { ...position } }),
  setKnob: (id, value) =>
    set((state) => ({ position: { ...state.position, [id]: value } })),
  replaceCache: (cache) => set({ cache: new Map(cache) }),
  putCachedObservation: (key, observations) =>
    set((state) => {
      const cache = new Map(state.cache)
      cache.set(key, observations)
      return { cache }
    }),
}))
