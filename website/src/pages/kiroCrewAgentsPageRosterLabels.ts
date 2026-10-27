/**
 * The words a roster card and row show for a crewmate's bindings: display
 * names and plain labels, never the internal ids the binding stores.
 *
 * - Built from: the same names the editor's Built From shows
 *   (`components/crew/builtFromName`). A crewmate bound to its own file
 *   (`kiro_agent` equal to its key) is named by its worker kit's template.
 * - Memory store: whether the memory is the crewmate's own or shared, from the
 *   same `memberMemoryState` the editor's memory row reads; the store id is a
 *   generated directory name nobody chose.
 */
import { i18nT } from '../i18n/t'
import { DEFAULT_TEMPLATE, mateAbilitiesLabel, templateDisplayName } from '../components/crew/builtFromName'
import { memberMemoryState } from './KiroCrewAgentsPageFields'

export type MemoryStores = Record<string, { memory_version?: number; owner_member?: string }>

/** What a roster cell shows for a crewmate's memory store. */
export function memoryStoreLabel(member: string, store: string, stores: MemoryStores | undefined): string {
  if (!stores && member !== 'default') return ''
  const state = memberMemoryState(member, store, stores)
  if (state === 'private') return i18nT('pages.kiroCrewAgentsPage.memory_label_private')
  if (state === 'legacy') return i18nT('pages.kiroCrewAgentsPage.memory_label_shared')
  return i18nT('pages.kiroCrewAgentsPage.memory_label_check')
}

/**
 * The label a roster cell shows for "Built from".
 *
 * A binding whose `kiro_agent` is the crewmate's own key owns its file: its
 * abilities are the sum of its worker base plus whatever was added to it, not a
 * single template, so it is labelled generically as a mate. Any other binding
 * is named by the shared template it points at.
 */
export function rosterBuiltFrom(agent: { name: string; kiro_agent: string }): { label: string } {
  const ownsFile = !!agent.kiro_agent && agent.kiro_agent === agent.name && agent.kiro_agent !== DEFAULT_TEMPLATE
  return { label: ownsFile ? mateAbilitiesLabel() : templateDisplayName(agent.kiro_agent) }
}
