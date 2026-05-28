// Component test for HarmonizationTab.
//
// Tests the cross-department harmonization view: loading state, business case
// grouping by department, net view display, and edit permissions.
// Phase 10, plan 10-05 T07.

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'

import HarmonizationTab from '@/components/HarmonizationTab.vue'
import { useSessionStore, type LoginPayload } from '@/stores/session'

// Mock the harmonization API
const mockGetHarmonization = vi.fn()
const mockDeleteHarmonization = vi.fn()

vi.mock('@/api/harmonization', () => ({
  getHarmonization: (...args: unknown[]) => mockGetHarmonization(...args),
  deleteHarmonization: (...args: unknown[]) => mockDeleteHarmonization(...args),
  putHarmonization: vi.fn(),
}))

// Stub all Vuetify components
const stubs = {
  'v-progress-linear': { template: '<div class="v-progress-linear-stub" />' },
  'v-alert': { props: ['type', 'text'], template: '<div class="v-alert-stub">{{ text }}</div>' },
  'v-card': { template: '<div class="v-card-stub"><slot /><slot name="text" /></div>' },
  'v-card-item': { template: '<div class="v-card-item-stub"><slot /></div>' },
  'v-card-title': { template: '<div class="v-card-title-stub"><slot /></div>' },
  'v-card-text': { template: '<div class="v-card-text-stub"><slot /></div>' },
  'v-icon': { template: '<i class="v-icon-stub" />' },
  'v-spacer': { template: '<span />' },
  'v-btn': { props: ['icon'], emits: ['click'], template: '<button class="v-btn-stub" @click="$emit(\'click\')"><slot /></button>' },
  'v-textarea': { template: '<textarea class="v-textarea-stub" />' },
  BusinessCaseCard: { props: ['bcase'], template: '<div class="bc-card-stub" :data-id="bcase.id" />' },
  NetViewEditor: {
    props: ['topicId', 'netView', 'canEdit'],
    emits: ['saved', 'deleted'],
    template: '<div class="net-view-editor-stub" :data-can-edit="canEdit" :data-has-view="!!netView" />',
  },
}

const TOPIC_ID = 'topic-001'

const DEPT_A = { id: 'dept-a', name: 'Retail', slug: 'retail', role: 'dept_lead' as const }
const DEPT_B = { id: 'dept-b', name: 'Finance', slug: 'finance', role: 'viewer' as const }

function loginPayload(overrides: Partial<LoginPayload> = {}): LoginPayload {
  return {
    ok: true,
    username: 'tester',
    is_superadmin: false,
    departments: [DEPT_A, DEPT_B],
    ...overrides,
  }
}

function makeResponse(opts: { cases?: number; netView?: boolean } = {}) {
  const cases = []
  for (let i = 0; i < (opts.cases ?? 0); i++) {
    cases.push({
      id: `bc-${i}`,
      department: i % 2 === 0 ? { id: 'dept-a', name: 'Retail' } : { id: 'dept-b', name: 'Finance' },
      framework: { id: 'fw-1', key: 'verdict', name: 'Verdict', display_component: 'VerdictCard' },
      structured_output: { verdict: 'relevant' },
      relevance_verdict: 'relevant',
      importance_score: 7,
      confidence: 0.85,
      created_at: '2026-05-28T10:00:00Z',
      model_used: 'gpt-4',
    })
  }
  return {
    topic: { id: TOPIC_ID, title: 'Test Topic', description: null, first_seen_at: '2026-05-28', last_seen_at: '2026-05-28' },
    business_cases: cases,
    net_view: opts.netView
      ? { text: 'Summary view', authored_by: { id: 'u1', username: 'admin' }, authored_at: '2026-05-28T10:00:00Z', updated_at: '2026-05-28T11:00:00Z' }
      : null,
  }
}

describe('HarmonizationTab', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('shows loading state then renders empty', async () => {
    mockGetHarmonization.mockResolvedValue(makeResponse())
    const session = useSessionStore()
    session.applyLoginResponse(loginPayload())
    session.switchDepartment(DEPT_A.id)

    const wrapper = mount(HarmonizationTab, {
      props: { topicId: TOPIC_ID },
      global: { stubs },
    })

    // Initially loading
    expect(wrapper.find('.v-progress-linear-stub').exists()).toBe(true)

    await flushPromises()

    // After load, no progress bar
    expect(wrapper.find('.v-progress-linear-stub').exists()).toBe(false)
    // NetViewEditor rendered
    expect(wrapper.find('.net-view-editor-stub').exists()).toBe(true)
  })

  it('renders business cases grouped by department', async () => {
    mockGetHarmonization.mockResolvedValue(makeResponse({ cases: 4 }))
    const session = useSessionStore()
    session.applyLoginResponse(loginPayload())
    session.switchDepartment(DEPT_A.id)

    const wrapper = mount(HarmonizationTab, {
      props: { topicId: TOPIC_ID },
      global: { stubs },
    })
    await flushPromises()

    const cards = wrapper.findAll('.bc-card-stub')
    expect(cards.length).toBe(4)
  })

  it('passes canEdit=true to NetViewEditor for dept_lead', async () => {
    mockGetHarmonization.mockResolvedValue(makeResponse({ netView: true }))
    const session = useSessionStore()
    session.applyLoginResponse(loginPayload())
    session.switchDepartment(DEPT_A.id)

    const wrapper = mount(HarmonizationTab, {
      props: { topicId: TOPIC_ID },
      global: { stubs },
    })
    await flushPromises()

    const editor = wrapper.find('.net-view-editor-stub')
    expect(editor.attributes('data-can-edit')).toBe('true')
  })

  it('passes canEdit=false to NetViewEditor for viewer', async () => {
    mockGetHarmonization.mockResolvedValue(makeResponse({ netView: true }))
    const session = useSessionStore()
    session.applyLoginResponse(loginPayload())
    session.switchDepartment(DEPT_B.id)

    const wrapper = mount(HarmonizationTab, {
      props: { topicId: TOPIC_ID },
      global: { stubs },
    })
    await flushPromises()

    const editor = wrapper.find('.net-view-editor-stub')
    expect(editor.attributes('data-can-edit')).toBe('false')
  })

  it('shows error alert on API failure', async () => {
    mockGetHarmonization.mockRejectedValue(new Error('Network error'))
    const session = useSessionStore()
    session.applyLoginResponse(loginPayload())
    session.switchDepartment(DEPT_A.id)

    const wrapper = mount(HarmonizationTab, {
      props: { topicId: TOPIC_ID },
      global: { stubs },
    })
    await flushPromises()

    expect(wrapper.find('.v-alert-stub').text()).toContain('Network error')
  })

  it('reloads when topicId prop changes', async () => {
    mockGetHarmonization.mockResolvedValue(makeResponse())
    const session = useSessionStore()
    session.applyLoginResponse(loginPayload())
    session.switchDepartment(DEPT_A.id)

    const wrapper = mount(HarmonizationTab, {
      props: { topicId: TOPIC_ID },
      global: { stubs },
    })
    await flushPromises()
    expect(mockGetHarmonization).toHaveBeenCalledTimes(1)

    await wrapper.setProps({ topicId: 'topic-002' })
    await flushPromises()
    expect(mockGetHarmonization).toHaveBeenCalledTimes(2)
    expect(mockGetHarmonization).toHaveBeenLastCalledWith('topic-002')
  })

  it('handles delete event from NetViewEditor', async () => {
    mockGetHarmonization.mockResolvedValue(makeResponse({ netView: true }))
    mockDeleteHarmonization.mockResolvedValue(undefined)
    const session = useSessionStore()
    session.applyLoginResponse(loginPayload())
    session.switchDepartment(DEPT_A.id)

    const wrapper = mount(HarmonizationTab, {
      props: { topicId: TOPIC_ID },
      global: { stubs },
    })
    await flushPromises()

    // Simulate delete event
    const editor = wrapper.findComponent({ name: 'NetViewEditor' })
    editor.vm.$emit('deleted')
    await flushPromises()

    expect(mockDeleteHarmonization).toHaveBeenCalledWith(TOPIC_ID)
  })
})
