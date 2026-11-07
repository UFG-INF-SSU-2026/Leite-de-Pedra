import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Em produção, o backend serve o build em https://<backend>/painel/ (mesma origem da API).
// Em desenvolvimento, o Vite repassa a API ao backend validando o certificado pela CA do
// projeto (NODE_EXTRA_CA_CERTS no script dev), sem desligar a verificação TLS.
const backend = 'https://localhost:8444'

export default defineConfig({
  base: '/painel/',
  plugins: [react()],
  server: {
    proxy: {
      '/admin': { target: backend, changeOrigin: true, secure: true },
      '/sessoes': { target: backend, changeOrigin: true, secure: true },
    },
  },
})
