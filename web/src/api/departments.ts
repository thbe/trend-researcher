// Departments + members API wrapper (Phase 10 MT-001/MT-002).
//
// Backed by services/api/src/api/routes/departments.py. All requests go
// through the shared client so the X-Active-Department header is injected
// where relevant (not for /api/departments itself, but for any per-dept
// follow-up the SPA does after picking one).

import { request } from './client'

export type DepartmentRole = 'viewer' | 'analyst' | 'dept_lead'

export interface Department {
  id: string
  name: string
  slug: string
  description: string | null
  created_at: string
  updated_at: string
}

export interface DepartmentsListResponse {
  departments: Department[]
  total: number
}

export interface Member {
  user_id: string
  username: string
  role: DepartmentRole
  created_at: string
  updated_at: string
}

export interface MembersListResponse {
  members: Member[]
  total: number
}

export interface DepartmentCreate {
  name: string
  slug: string
  description?: string | null
}

export interface DepartmentUpdate {
  name?: string
  description?: string | null
}

export interface MemberCreate {
  user_id: string
  role: DepartmentRole
}

export interface MemberUpdate {
  role: DepartmentRole
}

export function listDepartments(): Promise<DepartmentsListResponse> {
  // /api/departments doesn't need X-Active-Department — it's the discovery
  // surface the SPA hits before picking one. The header is harmless either
  // way (backend ignores it on this route) so we don't bother stripping it.
  return request<DepartmentsListResponse>('/api/departments')
}

export function getDepartment(id: string): Promise<Department> {
  return request<Department>(`/api/departments/${id}`)
}

export function createDepartment(body: DepartmentCreate): Promise<Department> {
  return request<Department>('/api/departments', { method: 'POST', body })
}

export function updateDepartment(id: string, body: DepartmentUpdate): Promise<Department> {
  return request<Department>(`/api/departments/${id}`, { method: 'PUT', body })
}

export function deleteDepartment(id: string): Promise<void> {
  return request<void>(`/api/departments/${id}`, { method: 'DELETE' })
}

export function listMembers(deptId: string): Promise<MembersListResponse> {
  return request<MembersListResponse>(`/api/departments/${deptId}/members`)
}

export function addMember(deptId: string, body: MemberCreate): Promise<Member> {
  return request<Member>(`/api/departments/${deptId}/members`, {
    method: 'POST',
    body,
  })
}

export function updateMember(
  deptId: string,
  userId: string,
  body: MemberUpdate,
): Promise<Member> {
  return request<Member>(`/api/departments/${deptId}/members/${userId}`, {
    method: 'PUT',
    body,
  })
}

export function removeMember(deptId: string, userId: string): Promise<void> {
  return request<void>(`/api/departments/${deptId}/members/${userId}`, {
    method: 'DELETE',
  })
}
