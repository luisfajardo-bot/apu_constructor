import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { AuthProvider } from "@/lib/auth";
// Fuentes auto-hospedadas, NO el CDN de Google. La CSP de producción es
// `default-src 'self'` sin `font-src` y `style-src 'self' 'unsafe-inline'` sin
// fonts.googleapis.com (apu_tool/servicio/seguridad_headers.py), así que un <link>
// al CDN andaría en `vite dev` —que no manda CSP— y fallaría en Render. Vite las
// empaqueta en dist/assets y las sirve el mismo origen. 84 KB las dos.
// Van ANTES de index.css para que el @font-face exista cuando se aplique --font-sans.
import "@fontsource-variable/inter-tight";
import "@fontsource-variable/jetbrains-mono";
import "./index.css";
import App from "./App.tsx";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
