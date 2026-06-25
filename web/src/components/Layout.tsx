import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { Toaster } from "sonner";
import { getStatus } from "@/api/corridas";
import type { StatusResponse } from "@/lib/tipos";

const NAV_LINKS = [
  { to: "/corridas", label: "Corridas", end: false },
  { to: "/insumos", label: "Insumos", end: true },
];

export default function Layout() {
  const [status, setStatus] = useState<StatusResponse | null>(null);

  useEffect(() => {
    getStatus()
      .then(setStatus)
      .catch(() => {
        /* sin backend — silencioso */
      });
  }, []);

  const chipText = status
    ? `${status.insumos} insumos · ${status.apus} APUs · IA: ${status.ia ? "habilitada" : "fallback"}`
    : "cargando…";

  return (
    <div style={styles.root}>
      {/* Barra superior */}
      <header style={styles.topbar}>
        <span style={styles.brand}>Armador de APUs</span>
        <span style={styles.chip}>{chipText}</span>
      </header>

      <div style={styles.body}>
        {/* Navegacion lateral */}
        <nav style={styles.sidebar}>
          <ul style={styles.navList}>
            {NAV_LINKS.map(({ to, label, end }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  end={end}
                  style={({ isActive }) => ({
                    ...styles.navLink,
                    ...(isActive ? styles.navLinkActive : {}),
                  })}
                >
                  {label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

        {/* Contenido principal */}
        <main style={styles.main}>
          <Outlet />
        </main>
      </div>
      <Toaster richColors position="top-right" />
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  root: {
    display: "flex",
    flexDirection: "column",
    height: "100vh",
    fontFamily: "system-ui, sans-serif",
    fontSize: "13px",
  },
  topbar: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "0 12px",
    height: "36px",
    background: "#1a1a2e",
    color: "#e2e8f0",
    flexShrink: 0,
  },
  brand: {
    fontWeight: 600,
    fontSize: "13px",
    letterSpacing: "0.02em",
  },
  chip: {
    fontSize: "11px",
    background: "rgba(255,255,255,0.08)",
    padding: "2px 8px",
    borderRadius: "10px",
    color: "#a0aec0",
    whiteSpace: "nowrap",
  },
  body: {
    display: "flex",
    flex: 1,
    overflow: "hidden",
  },
  sidebar: {
    width: "140px",
    background: "#f7f7f8",
    borderRight: "1px solid #e2e8f0",
    flexShrink: 0,
    paddingTop: "8px",
  },
  navList: {
    listStyle: "none",
    margin: 0,
    padding: 0,
  },
  navLink: {
    display: "block",
    padding: "6px 14px",
    color: "#4a5568",
    textDecoration: "none",
    fontSize: "13px",
    borderLeft: "3px solid transparent",
  },
  navLinkActive: {
    color: "#1a1a2e",
    fontWeight: 600,
    borderLeft: "3px solid #4a90d9",
    background: "#edf2f7",
  },
  main: {
    flex: 1,
    overflow: "auto",
    background: "#ffffff",
  },
};
