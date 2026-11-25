import './asaas-ui/styles/index.css';
import './styles/site.css';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { Ambient, ToastProvider } from './asaas-ui';
import { AuthProvider } from './lib/auth';
import { LanguageProvider } from './lib/i18n';
import App from './App';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <LanguageProvider>
      <ToastProvider>
        <Ambient />
        <BrowserRouter>
          <AuthProvider>
            <App />
          </AuthProvider>
        </BrowserRouter>
      </ToastProvider>
    </LanguageProvider>
  </StrictMode>,
);
