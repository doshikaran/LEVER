import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Permalinks `/m/:changeId` must resolve to the SPA in local preview/deploy.
  appType: 'spa',
})
