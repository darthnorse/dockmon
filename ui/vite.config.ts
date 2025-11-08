import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  base: process.env.BASE_PATH || '/',
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: parseInt(process.env.VITE_PORT || '3000'),  // Allow override via VITE_PORT env var
    proxy: {
      // Proxy API requests to backend during development
      '/api': {
        target: 'https://localhost:8001',
        changeOrigin: true,
        secure: false, // Allow self-signed certs in dev
      },
      '/ws': {
        target: 'wss://localhost:8001',
        ws: true,
        secure: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false, // Disable in production
    rollupOptions: {
      output: {
        manualChunks: {
          // Split vendor chunks for better caching
          react: ['react', 'react-dom', 'react-router-dom'],
          query: ['@tanstack/react-query'],
        },
      },
    },
    chunkSizeWarningLimit: 500, // 500KB warning threshold
  },
})
