import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/data': 'http://localhost:8000',
    },
  },
  build: {
    outDir: '../modern_opalx_regsuite/static',
    emptyOutDir: true,
  },
})
