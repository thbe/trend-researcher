// Component test for DepartmentSwitcher.
//
// The switcher has two render modes: a v-select when the user belongs to
// 2+ departments, and a static label when they belong to exactly 1.
// Vuetify components are stubbed (we are testing OUR component logic,
// not Vuetify rendering) and we assert on the chosen mode + the wiring
// between the v-model and session.switchDepartment.

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'

import DepartmentSwitcher from '@/components/DepartmentSwitcher.vue'
import { useSessionStore, type LoginPayload } from '@/stores/session'

vi.mock('@/stores/frameworks', () => ({
  useFrameworksStore: () => ({ loadMine: vi.fn().mockResolvedValue(undefined) }),
}))

const DEPT_A = {
  id: 'aaaa1111-0000-0000-0000-000000000001',
  name: 'Alpha',
  slug: 'alpha',
  role: 'analyst' as const,
}
const DEPT_B = {
  id: 'bbbb2222-0000-0000-0000-000000000002',
  name: 'Bravo',
  slug: 'bravo',
  role: 'dept_lead' as const,
}

function payload(overrides: Partial<LoginPayload> = {}): LoginPayload {
  return {
    ok: true,
    username: 'tester',
    is_superadmin: false,
    departments: [DEPT_A, DEPT_B],
    ...overrides,
  }
}

// Minimal stubs that preserve the props/events we assert against.
// NOTE: template strings here are compiled by Vue's RUNTIME compiler at
// mount time — they must be plain JS, no TypeScript syntax (no `as X`).
const stubs = {
  'v-select': {
    props: ['modelValue', 'items', 'label'],
    emits: ['update:modelValue'],
    template: `
      <select
        class="v-select-stub"
        :data-label="label"
        :value="modelValue"
        @change="$emit('update:modelValue', $event.target.value)"
      >
        <option v-for="o in items" :key="o.value" :value="o.value">{{ o.title }}</option>
      </select>`,
  },
  'v-icon': { template: '<i class="v-icon-stub" />' },
} as const

describe('DepartmentSwitcher.vue', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('renders nothing when the user is unauthenticated', () => {
    const wrapper = mount(DepartmentSwitcher, { global: { stubs } })
    expect(wrapper.find('.v-select-stub').exists()).toBe(false)
    expect(wrapper.text()).toBe('')
  })

  it('renders a v-select with one option per department when there are 2+', () => {
    const s = useSessionStore()
    s.applyLoginResponse(payload())

    const wrapper = mount(DepartmentSwitcher, { global: { stubs } })
    const select = wrapper.find('select.v-select-stub')
    expect(select.exists()).toBe(true)
    expect(select.attributes('data-label')).toBe('Active department')
    const options = select.findAll('option')
    expect(options.map((o) => o.text())).toEqual(['Alpha', 'Bravo'])
    expect((select.element as HTMLSelectElement).value).toBe(DEPT_A.id)
  })

  it('changing the v-select value calls session.switchDepartment', async () => {
    const s = useSessionStore()
    s.applyLoginResponse(payload())
    const spy = vi.spyOn(s, 'switchDepartment')

    const wrapper = mount(DepartmentSwitcher, { global: { stubs } })
    const select = wrapper.find('select.v-select-stub')
    await select.setValue(DEPT_B.id)

    expect(spy).toHaveBeenCalledWith(DEPT_B.id)
  })

  it('renders a static label (no select) when the user has exactly one department', () => {
    const s = useSessionStore()
    s.applyLoginResponse(payload({ departments: [DEPT_A] }))

    const wrapper = mount(DepartmentSwitcher, { global: { stubs } })
    expect(wrapper.find('select.v-select-stub').exists()).toBe(false)
    expect(wrapper.text()).toContain('Alpha')
  })
})
