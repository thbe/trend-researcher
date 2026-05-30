// Vuetify 3 plugin — thbe brand palette (UI-SPEC 04-UI-SPEC.md).
// 60/30/10 color discipline: neutral surfaces dominate, secondary slate
// for chrome, primary "Punch Red" reserved for accents (hover tints,
// sort chevrons, focus rings, external-link icons, and primary CTAs).
//
// Button hierarchy (post-Phase-4 extension):
//   - Primary CTA       → explicit `variant="flat" color="primary"` per call-site
//                         (white-on-red, AA contrast, unmistakable affordance)
//   - Secondary action  → explicit `variant="tonal"`
//   - Tertiary / icon   → default `variant="text"` (declared below)
// Rationale: Phase 4 spec only budgeted for two read-only views and zero
// CTAs, so the global `text` default was correct then. As the app grew
// (Login, Assessment, AIConfig …) CTAs need a solid affordance. We keep
// `text` as the *default* so accidental `<v-btn>` instances stay quiet,
// and require call-sites to opt in to flat/tonal for real actions.
import 'vuetify/styles'
import { createVuetify } from 'vuetify'

export default createVuetify({
  theme: {
    defaultTheme: 'thbeLight',
    themes: {
      thbeLight: {
        dark: false,
        colors: {
          primary: '#EF233C',      // Punch Red — accent + primary CTAs
          secondary: '#62727B',    // Slate — chrome / icons / secondary actions
          success: '#10B981',
          error: '#B00020',
          info: '#0288D1',
          warning: '#F59E0B',
          background: '#FAFAFA',
          surface: '#FFFFFF',
        },
      },
    },
  },
  defaults: {
    VBtn: {
      // Default stays `text` per UI-SPEC §Color (accent discipline).
      // Real CTAs override this with `variant="flat"`.
      variant: 'text',
    },
    VCard: {
      rounded: 'lg',
    },
    VTextField: {
      variant: 'outlined',
      density: 'comfortable',
    },
    VTextarea: {
      variant: 'outlined',
      density: 'comfortable',
    },
    VSelect: {
      variant: 'outlined',
      density: 'comfortable',
    },
    VCombobox: {
      variant: 'outlined',
      density: 'comfortable',
    },
  },
})
