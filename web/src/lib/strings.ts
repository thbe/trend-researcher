// Rename hook (G8): change APP_NAME / APP_TAGLINE here when the product is
// renamed. All product-facing strings funnel through this module so the
// rename is a one-file edit (CONTEXT G8 — Phase 10).
//
// Generic UI strings ("Save", "Cancel", "Close") may stay inline at call
// sites; only product/brand strings + page titles + nav labels live here.

export const STRINGS = {
  APP_NAME: 'Trend Researcher',
  APP_TAGLINE: 'Market Intelligence Platform',

  // Page titles
  PAGE_DASHBOARD: 'Dashboard',
  PAGE_TOPICS: 'Topics',
  PAGE_TOPIC_DETAIL: 'Topic Detail',
  PAGE_ASSESSMENT: 'Assessment',
  PAGE_AI_CONFIG: 'AI Configuration',
  PAGE_SOURCES: 'Sources',
  PAGE_FRAMEWORK_SETTINGS: 'Framework Settings',
  PAGE_USERS: 'Users',
  PAGE_DEPARTMENTS: 'Departments',
  PAGE_DEPARTMENT_SETTINGS: 'Department Settings',
  PAGE_LOGIN: 'Sign In',

  // Nav labels
  NAV_DASHBOARD: 'Dashboard',
  NAV_TOPICS: 'Topics',
  NAV_ASSESSMENT: 'Assess',
  NAV_AI_CONFIG: 'AI Config',
  NAV_SOURCES: 'Sources',
  NAV_FRAMEWORK_SETTINGS: 'Framework Settings',
  NAV_ADMIN: 'Admin',

  // Buttons / key labels
  BTN_SIGN_IN: 'Sign In',
  BTN_SIGN_OUT: 'Sign Out',

  // Misc
  LABEL_ACTIVE_DEPT: 'Active department',
  LABEL_SUPERADMIN: 'Superadmin',
} as const

export type StringKey = keyof typeof STRINGS
