// Role helpers — single source of truth for per-department RBAC ordinals.
//
// SECURITY NOTE: Hiding a button based on these helpers is UX gating only.
// Backend (services/api) enforces every dept-scoped permission via the
// require_role dependency. A `viewer` who guesses the URL of an Assess
// endpoint will still get a 403 from the API.

export const ROLES = ['viewer', 'analyst', 'dept_lead'] as const
export type Role = (typeof ROLES)[number]

const ORDINAL: Record<Role, number> = {
  viewer: 0,
  analyst: 1,
  dept_lead: 2,
}

/** Returns true when `current` is at least `required` in the role hierarchy. */
export function roleAtLeast(current: Role, required: Role): boolean {
  return ORDINAL[current] >= ORDINAL[required]
}

export function isRole(value: unknown): value is Role {
  return typeof value === 'string' && (ROLES as readonly string[]).includes(value)
}
