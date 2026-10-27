import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, fireEvent } from '@testing-library/react'
import MarkdownRenderer from '../components/MarkdownRenderer'

/**
 * Markdown has no video syntax, so a message references a recording as
 * `![demo](clip.mp4)`. That used to render an <img>, which cannot play a clip
 * (and /api/file-raw refuses a non-image body), so the reader saw the broken-
 * image chip (#14909). A video or audio extension now renders a player: a local
 * file streams from /api/file-stream, and a remote one goes through the same
 * click-to-load gate as a raw-HTML <video>/<audio>.
 */

const LOCAL_VIDEO = '/home/user/project/shots/demo.mp4'
const LOCAL_AUDIO = '/home/user/project/shots/voice.mp3'
const LOCAL_IMAGE = '/home/user/project/shots/settings.png'

const fetchMock = vi.fn()

beforeEach(() => {
  fetchMock.mockReset()
  fetchMock.mockResolvedValue({ status: 404 })
  vi.stubGlobal('fetch', fetchMock)
})

function streamUrl(path: string): string {
  return `/api/file-stream?path=${encodeURIComponent(path)}`
}

describe('markdown media references', () => {
  it('a local video reference renders a player that streams the file, not an <img>', () => {
    const { container } = render(<MarkdownRenderer content={`![Demo recording](${LOCAL_VIDEO})`} />)
    const video = container.querySelector('video')
    expect(video).not.toBeNull()
    expect(video!.getAttribute('src')).toBe(streamUrl(LOCAL_VIDEO))
    expect(video!.hasAttribute('controls')).toBe(true)
    expect(video!.getAttribute('aria-label')).toBe('Demo recording')
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('[data-testid="md-broken-image-chip"]')).toBeNull()
  })

  it('a local audio reference renders an audio player', () => {
    const { container } = render(<MarkdownRenderer content={`![voice note](${LOCAL_AUDIO})`} />)
    const audio = container.querySelector('audio')
    expect(audio).not.toBeNull()
    expect(audio!.getAttribute('src')).toBe(streamUrl(LOCAL_AUDIO))
    expect(container.querySelector('img')).toBeNull()
  })

  it('an image reference still renders an image', () => {
    const { container } = render(<MarkdownRenderer content={`![Settings page](${LOCAL_IMAGE})`} />)
    expect(container.querySelector('img')).not.toBeNull()
    expect(container.querySelector('video')).toBeNull()
  })

  it('a remote video waits behind the click-to-load gate and fetches nothing first', () => {
    const { container, getByText } = render(
      <MarkdownRenderer content={'![clip](https://media.example/clips/demo.mp4)'} />,
    )
    expect(container.querySelector('video')).toBeNull()
    expect(container.querySelector('img')).toBeNull()
    getByText('External video blocked — click to load')
    fireEvent.click(container.querySelector('button')!)
    const video = container.querySelector('video')
    expect(video).not.toBeNull()
    expect(video!.getAttribute('src')).toBe('https://media.example/clips/demo.mp4')
  })

  it('a media extension in a query string does not make an image a video', () => {
    const { container } = render(
      <MarkdownRenderer content={'![chart](https://media.example/chart.png?format=.mp4)'} />,
    )
    expect(container.querySelector('video')).toBeNull()
  })

  it('a local clip that fails to load names a media failure and probes the stream route', async () => {
    const { container, findByText } = render(
      <MarkdownRenderer content={`![Demo recording](${LOCAL_VIDEO})`} />,
    )
    fireEvent.error(container.querySelector('video')!)
    await findByText('Media file no longer exists')
    expect(fetchMock).toHaveBeenCalledWith(streamUrl(LOCAL_VIDEO), { method: 'HEAD' })
  })
})
