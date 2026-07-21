import type { ReactElement } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, type RenderResult } from '@testing-library/react'

/**
 * App.tsx now reads/writes REST state (diff submission, pin, ledger) through
 * TanStack Query, which requires a `QueryClientProvider` ancestor — without
 * one, `useQuery`/`useMutation` throw immediately on render. Every test that
 * renders <App /> needs this wrapper. A fresh QueryClient is created per call
 * so query/mutation state (and its cache) never leaks between tests; retries
 * are disabled so a stubbed-fetch rejection in a test surfaces immediately
 * instead of being retried several times against fake timers/microtasks.
 */
export function renderWithQueryClient(ui: ReactElement): RenderResult {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}
