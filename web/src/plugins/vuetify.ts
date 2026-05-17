// Vuetify 3 plugin — thbe brand palette (UI-SPEC 04-UI-SPEC.md).
// 60/30/10 color discipline: neutral surfaces dominate, secondary slate
// for chrome, primary "Punch Red" reserved for accents (hover tints,
// sort chevrons, focus rings, external-link icons).
import 'vuetify/styles'
import { createVuetify } from 'vuetify'

export default createVuetify({
  theme: {
    defaultTheme: 'thbeLight',
    themes: {
      thbeLight: {
        dark: false,
        colors: {
          primary: '#EF233C',      // Punch Red — 10% accent only
          secondary: '#62727B',    // Slate — chrome / app-bar / icons
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
      variant: 'text',
    },
  },
})
