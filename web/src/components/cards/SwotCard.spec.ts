// Component test for SwotCard.
//
// SwotCard renders the four-quadrant SWOT layout from BusinessCase.
// structured_output. We assert the data extraction logic: which entries
// are pulled from which key, fallbacks to top-level BusinessCase fields,
// the verdict chip colour rule, and the empty-quadrant placeholder.

import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import type { Component } from 'vue'

import SwotCard from '@/components/cards/SwotCard.vue'
import type { BusinessCase } from '@/api/assessment'

// Stub Vuetify components down to plain wrappers that preserve text +
// attributes we want to assert on. We keep the per-component class so
// querySelectors stay readable.
const passthroughTemplates = [
  'v-card',
  'v-card-item',
  'v-card-title',
  'v-card-subtitle',
  'v-card-text',
  'v-row',
  'v-col',
  'v-list',
  'v-list-item',
  'v-list-item-title',
  'v-list-item-subtitle',
] as const

const stubs: Record<string, Component> = Object.fromEntries(
  passthroughTemplates.map((tag) => [
    tag,
    {
      inheritAttrs: false,
      template: `<div class="${tag}-stub" v-bind="$attrs"><slot name="prepend" /><slot /><slot name="append" /></div>`,
    },
  ]),
)
stubs['v-chip'] = {
  inheritAttrs: false,
  props: ['color'],
  template: `<span class="v-chip-stub" :data-color="color"><slot /></span>`,
}
stubs['v-icon'] = { template: '<i class="v-icon-stub" />' }

function baseCase(overrides: Partial<BusinessCase> = {}): BusinessCase {
  return {
    id: 'bc-1',
    topic_id: 'topic-1',
    title: 'A topic',
    relevance_verdict: 'relevant',
    relevance_reason: 'fallback reason',
    model_used: 'gpt-test',
    prompt_version: 'v1',
    generated_at: '2026-01-01T00:00:00Z',
    framework: {
      id: 'fw-swot',
      key: 'swot',
      name: 'SWOT Analysis',
      display_component: 'SwotCard',
    },
    structured_output: {
      verdict: 'relevant',
      importance: 7,
      confidence: 0.42,
      reason: 'Strong tailwind across segments.',
      strengths: [
        { point: 'Brand strength', rationale: 'High recall in target' },
        { point: 'Scale', rationale: 'Existing distribution' },
      ],
      weaknesses: [{ point: 'Margin', rationale: 'Thin' }],
      opportunities: [{ point: 'Cross-sell', rationale: 'Adjacent SKUs' }],
      threats: [],
    },
    ...overrides,
  }
}

describe('SwotCard.vue', () => {
  it('renders the four quadrant labels and the points within them', () => {
    const wrapper = mount(SwotCard, {
      props: { bcase: baseCase() },
      global: { stubs },
    })
    const text = wrapper.text()
    for (const label of ['Strengths', 'Weaknesses', 'Opportunities', 'Threats']) {
      expect(text).toContain(label)
    }
    expect(text).toContain('Brand strength')
    expect(text).toContain('High recall in target')
    expect(text).toContain('Margin')
    expect(text).toContain('Cross-sell')
  })

  it('shows the empty placeholder for quadrants with no entries', () => {
    const wrapper = mount(SwotCard, {
      props: { bcase: baseCase() },
      global: { stubs },
    })
    // Threats is empty in baseCase fixture.
    expect(wrapper.text()).toContain('— none —')
  })

  it('renders importance + confidence chips from structured_output', () => {
    const wrapper = mount(SwotCard, {
      props: { bcase: baseCase() },
      global: { stubs },
    })
    const text = wrapper.text()
    expect(text).toContain('Importance 7')
    expect(text).toContain('Confidence 42%')
  })

  it('uses success colour chip when verdict is relevant', () => {
    const wrapper = mount(SwotCard, {
      props: { bcase: baseCase() },
      global: { stubs },
    })
    const verdictChip = wrapper.find('.v-chip-stub')
    expect(verdictChip.attributes('data-color')).toBe('success')
    expect(verdictChip.text()).toBe('relevant')
  })

  it('uses grey colour chip when verdict is not relevant', () => {
    const c = baseCase({
      structured_output: {
        verdict: 'not_relevant',
        importance: null,
        confidence: null,
        reason: '',
        strengths: [],
        weaknesses: [],
        opportunities: [],
        threats: [],
      },
    })
    const wrapper = mount(SwotCard, { props: { bcase: c }, global: { stubs } })
    const verdictChip = wrapper.find('.v-chip-stub')
    expect(verdictChip.attributes('data-color')).toBe('grey')
    expect(verdictChip.text()).toBe('not_relevant')
  })

  it('falls back to top-level BusinessCase fields when structured_output is empty', () => {
    const c = baseCase({
      relevance_verdict: 'relevant',
      relevance_reason: 'top-level fallback reason',
      importance: 9,
      confidence: 0.8,
      structured_output: undefined,
    })
    const wrapper = mount(SwotCard, { props: { bcase: c }, global: { stubs } })
    const text = wrapper.text()
    expect(text).toContain('top-level fallback reason')
    expect(text).toContain('Importance 9')
    expect(text).toContain('Confidence 80%')
    // All four quadrants show the empty placeholder.
    const noneCount = (text.match(/— none —/g) ?? []).length
    expect(noneCount).toBe(4)
  })

  it('renders the framework name in the title and model+prompt in the subtitle', () => {
    const wrapper = mount(SwotCard, {
      props: { bcase: baseCase() },
      global: { stubs },
    })
    expect(wrapper.text()).toContain('SWOT Analysis')
    expect(wrapper.text()).toContain('gpt-test')
    expect(wrapper.text()).toContain('v1')
  })
})
