import axios from 'axios'

/**
 * API client for the MoDora orchestrator.
 *
 * - Dev: requests go to `/api/*` and Vite proxies to http://127.0.0.1:8888
 * - Prod: set VITE_API_BASE to the orchestrator URL at build time
 */
const baseURL = import.meta.env.VITE_API_BASE || '/api'

const http = axios.create({
  baseURL,
  timeout: 600_000, // 10 min — table filling can take a while
})

http.interceptors.response.use(
  (r) => r,
  (err) => {
    const detail = err.response?.data?.detail || err.message || '请求失败'
    return Promise.reject(new Error(detail))
  },
)

// ---------------------------------------------------------------------------
// Module 0: Health & history
// ---------------------------------------------------------------------------

export async function getHealth() {
  const { data } = await http.get('/health')
  return data
}

export async function getHistory(limit = 50) {
  const { data } = await http.get('/history', { params: { limit } })
  return data
}

// ---------------------------------------------------------------------------
// Module 1: Document edit
// ---------------------------------------------------------------------------

export async function docEdit(file, instruction) {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('instruction', instruction)
  const resp = await http.post('/doc-edit', fd, {
    responseType: 'blob',
  })
  return resp.data // Blob
}

// ---------------------------------------------------------------------------
// Module 2: Information extraction
// ---------------------------------------------------------------------------

export async function extractInfo(file, query = '') {
  const fd = new FormData()
  fd.append('file', file)
  if (query) fd.append('query', query)
  const { data } = await http.post('/extract', fd)
  return data
}

// ---------------------------------------------------------------------------
// Module 3: Table filling
// ---------------------------------------------------------------------------

/**
 * Upload reference materials. Each parameter is an array of File objects.
 */
export async function ingestMaterials({ excel = [], mdTxt = [], word = [] }) {
  const fd = new FormData()
  excel.forEach((f) => fd.append('ref_excel', f))
  mdTxt.forEach((f) => fd.append('ref_md_txt', f))
  word.forEach((f) => fd.append('ref_word', f))
  const { data } = await http.post('/ingest', fd)
  return data
}

export async function listMaterials() {
  const { data } = await http.get('/ingest')
  return data
}

export async function processTemplate(designFile, requirement = '') {
  const fd = new FormData()
  fd.append('design_file', designFile)
  fd.append('requirement', requirement)
  const resp = await http.post('/process', fd, { responseType: 'blob' })
  return resp.data // Blob
}

// ---------------------------------------------------------------------------
// Chat Agent (unified conversational entry point)
// ---------------------------------------------------------------------------

/**
 * Send a message to the chat agent.
 *   message: string
 *   history: prior messages [{role, content}]
 *   files:   File[]
 * Returns: { role, intent, content, result }
 */
export async function chatAgent({ message, history = [], files = [] }) {
  const fd = new FormData()
  fd.append('message', message)
  fd.append('history', JSON.stringify(history))
  files.forEach((f) => fd.append('files', f))
  const { data } = await http.post('/agent/chat', fd)
  return data
}

export function chatResultUrl(fileId) {
  return `${baseURL}/agent/chat/result/${encodeURIComponent(fileId)}`
}

// ---------------------------------------------------------------------------
// Auxiliary: file preview URL
// ---------------------------------------------------------------------------

export function previewUrl(filename) {
  return `${baseURL}/preview/${encodeURIComponent(filename)}`
}
