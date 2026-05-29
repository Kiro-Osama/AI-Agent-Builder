import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './index.css'
import { Toaster } from 'sonner'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
      <Toaster
        theme="dark"
        position="top-right"
        toastOptions={{
          style: {
            background: 'hsl(240 20% 8%)',
            border: '1px solid hsl(240 10% 15%)',
            color: 'hsl(228 20% 95%)',
          },
        }}
      />
    </BrowserRouter>
  </React.StrictMode>,
)
