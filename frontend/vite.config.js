import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  if (mode === 'production' && !env.VITE_API_BASE?.trim()) {
    throw new Error('VITE_API_BASE must be explicitly configured before a production build.')
  }
  return {
    plugins: [react()],
  }
})
