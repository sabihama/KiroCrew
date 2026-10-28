import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import SourcesList from '../pages/knowledge/SourcesList'
import * as api from '../pages/knowledge/api'
import { api as clientApi } from '../api/client'

vi.mock('../pages/knowledge/api', () => ({ knowledgeApi: vi.fn() }))
vi.mock('../api/client', () => ({ api: { dashboardConfig: vi.fn() } }))

// The Web Page form adds one https page as a source; the gateway fetches it
// only from a host in knowledge.doc_ingest_hosts, which the form names.

function renderList() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <SourcesList
        onIngest={() => {}}
        uploadNamespace="default"
        setUploadNamespace={() => {}}
        namespaces={['default']}
        ingestionJobs={[]}
        supportedFormatsDisplay=".md"
      />
    </QueryClientProvider>,
  )
}

function mockGateway(hosts: string[]) {
  vi.mocked(api.knowledgeApi).mockImplementation(((path: string, init?: RequestInit) => {
    if (path === '/config') return Promise.resolve({ enabled: true, supported_formats: ['.md'], url_allowed_hosts: hosts })
    if (path === '/sources' && init?.method === 'POST') return Promise.resolve({ id: 'src-1', status: 'created' })
    if (path === '/sources/src-1/sync') return Promise.resolve({ status: 'syncing' })
    return Promise.resolve([])
  }) as unknown as typeof api.knowledgeApi)
}

async function openWebPage() {
  fireEvent.click(await screen.findByText('+ Add Source'))
  fireEvent.click(screen.getByRole('button', { name: /Web Page/ }))
}

beforeEach(() => {
  vi.mocked(api.knowledgeApi).mockReset()
  vi.mocked(clientApi.dashboardConfig).mockReset()
  vi.mocked(clientApi.dashboardConfig).mockResolvedValue({})
})

describe('SourcesList web page source', () => {
  it('says nothing can be fetched while the host list is empty', async () => {
    mockGateway([])
    renderList()
    await openWebPage()
    expect(await screen.findByText(/That list is empty/)).toBeInTheDocument()
  })

  it('names the allowed hosts', async () => {
    mockGateway(['example.com'])
    renderList()
    await openWebPage()
    expect(await screen.findByText(/Allowed hosts: example\.com\./)).toBeInTheDocument()
  })

  it('adds the page as a url source and starts its fetch', async () => {
    mockGateway(['example.com'])
    renderList()
    await openWebPage()
    // A pasted link often ends in a newline; the form sends it trimmed.
    fireEvent.change(screen.getByLabelText('Page URL'), { target: { value: 'https://example.com/a\n' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add Page' }))
    await waitFor(() => {
      expect(api.knowledgeApi).toHaveBeenCalledWith('/sources/src-1/sync', { method: 'POST' })
    })
    const post = vi.mocked(api.knowledgeApi).mock.calls.find(([p, init]) => p === '/sources' && init?.method === 'POST')
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ name: 'https://example.com/a', source_type: 'url', uri: 'https://example.com/a' })
  })

  it('shows a refused host through the error notice', async () => {
    mockGateway([])
    const refused = 'Host other.com is not in knowledge.doc_ingest_hosts.'
    const base = vi.mocked(api.knowledgeApi).getMockImplementation()!
    vi.mocked(api.knowledgeApi).mockImplementation(((path: string, init?: RequestInit) =>
      path === '/sources' && init?.method === 'POST' ? Promise.reject(new Error(refused)) : base(path, init)) as unknown as typeof api.knowledgeApi)
    renderList()
    await openWebPage()
    fireEvent.change(screen.getByLabelText('Page URL'), { target: { value: 'https://other.com/a' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add Page' }))
    expect(await screen.findByTestId('sources-web-page-error')).toHaveTextContent(refused)
  })
})
