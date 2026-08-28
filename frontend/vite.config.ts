import react from '@vitejs/plugin-react'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'

declare const process: { env: Record<string, string | undefined> }

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        '/api': `http://127.0.0.1:${process.env.API_PORT || env.API_PORT || '8000'}`,
      },
    },
    test: {
      environment: 'jsdom',
      setupFiles: './src/test/setup.ts',
      globals: true,
      include: ['src/**/*.test.{ts,tsx}'],
    },
  }
})
