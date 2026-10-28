/**
 * The chat page's rows are the person's: a Crew Mode root's crew members are left
 * out ONCE, in `chatPageSlots`, which feeds the sidebar, the collapsed-sidebar
 * flyout (`SessionsSidebarChrome` passes `filteredSlots` to `SessionFlyout`) and
 * the unread count (`surfaceUnreadKeys`). Dropping `crewModeView` from
 * `chatPageSlots` reddens both tests.
 */
import { describe, expect, it } from 'vitest'
import type { ChatSlot } from '../../../types'
import { chatPageSlots, surfaceUnreadKeys } from './pageEnvironment'

const row = (key: string, extra: Partial<ChatSlot> = {}): ChatSlot => ({
  key, title: key, messages: 1, running: false, mode: '', ...extra,
} as ChatSlot)

const ROWS = [
  row('plain'),
  row('root', { crew_mode_root: true }),
  row('member', { crew_root: 'root' }),
  row('slack-1', { surface: 'slack' }),
]

describe('chatPageSlots -- the flyout and sidebar input', () => {
  it('keeps the person\'s chat rows and the root, drops crew members and other surfaces', () => {
    expect(chatPageSlots(ROWS).map(s => s.key)).toEqual(['plain', 'root'])
  })

  it('leaves a list with no crew untouched', () => {
    const plain = [row('a'), row('b')]
    expect(chatPageSlots(plain)).toEqual(plain)
  })
})

describe('surfaceUnreadKeys -- the unread count', () => {
  it('counts unread only on rows the page shows: a crew member\'s unread never counts', () => {
    const visible = chatPageSlots(ROWS)
    expect(surfaceUnreadKeys(['member', 'plain', 'slack-1'], visible)).toEqual(['plain'])
    expect(surfaceUnreadKeys([], visible)).toEqual([])
  })
})
