import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

const buildDir = process.env.KB_FRONTEND_BUILD_DIR
  ? path.resolve(process.env.KB_FRONTEND_BUILD_DIR)
  : '<project-root>/knowledge-base/.frontend-build-runtime-user8'

export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: buildDir,
    assetsDir: 'assets',
    emptyOutDir: true
  },
  server: {
    host: '0.0.0.0',
    port: 3031,
    proxy: {
      '/search': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/tasks': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/stats': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/health': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/hybrid-status': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/upload': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/files': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/category-relevance': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/analyze-question': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/admin': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/skills': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/ws': {
        target: 'ws://localhost:8000',
        changeOrigin: true,
        ws: true
      }
    }
  }
})
