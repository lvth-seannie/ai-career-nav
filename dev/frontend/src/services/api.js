// Talks directly to the Django backend (see backend/api). Configure the base
// URL via VITE_API_URL (see .env.example); defaults to the local dev server.
const API_BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api'

async function apiFetch(path, options) {
  const response = await fetch(`${API_BASE_URL}${path}`, options)

  if (!response.ok) {
    throw new Error(`Request to ${path} failed (${response.status})`)
  }

  return response.json()
}

export async function submitCareerAnalysis({ targetRole, currentSkills }) {
  return apiFetch('/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ targetRole, currentSkills }),
  })
}

export async function fetchMarketInsights() {
  return apiFetch('/market-insights')
}

export async function fetchRoles() {
  const { roles } = await apiFetch('/roles')
  return roles
}
