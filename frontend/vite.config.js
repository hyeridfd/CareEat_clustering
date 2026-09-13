import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // 외부(다른 와이파이·데이터)에서 테스트할 때 쓰는 임시 터널 주소 허용
    allowedHosts: ['.trycloudflare.com', '.ngrok-free.app'],
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      }
    }
  }
})
