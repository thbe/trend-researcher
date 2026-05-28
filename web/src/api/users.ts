// User management API client (superadmin only).

import { request } from './client'

export interface UserResponse {
  id: string
  username: string
  is_active: boolean
  is_superadmin: boolean
  created_at: string
}

export interface UsersListResponse {
  users: UserResponse[]
}

export interface UserCreateRequest {
  username: string
  password: string
  is_superadmin: boolean
}

export async function listUsers(): Promise<UsersListResponse> {
  return request<UsersListResponse>('/api/users')
}

export async function createUser(body: UserCreateRequest): Promise<UserResponse> {
  return request<UserResponse>('/api/users', { method: 'POST', body })
}

export async function deleteUser(userId: string): Promise<void> {
  await request<void>(`/api/users/${userId}`, { method: 'DELETE' })
}
