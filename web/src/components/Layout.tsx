import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { Toaster } from "sonner";
import { getStatus } from "@/api/corridas";
import type { StatusResponse } from "@/lib/tipos";
import { useAuth } from "@/lib/auth";
import { puede } from "@/components/rutas";

export default function Layout() {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const { perfil, logout } = useAuth();

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

  const links = [
    { to: "/corridas", label: "Corridas", end: false },
    { to: "/insumos", label: "Insumos", end: true },
    { to: "/apus", label: "APUs", end: true },
    ...(puede(perfil?.rol, "admin") ? [{ to: "/usuarios", label: "Usuarios", end: true }] : []),
  ];

  return (
    <div style={styles.root}>
      {/* Barra superior */}
      <header style={styles.topbar}>
        <div style={styles.topbarLeft}>
          <span style={styles.brand}>Armador de APUs</span>
          <span style={styles.chip}>{chipText}</span>
        </div>
        {perfil && (
          <div style={styles.userMenu}>
            <span style={styles.userIdentity}>
              <span style={styles.userEmail}>{perfil.email}</span>
              <span style={styles.userRoleDot}>·</span>
              <span style={styles.userRole}>{perfil.rol}</span>
            </span>
            <button
              type="button"
              onClick={() => logout()}
              style={styles.logoutButton}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = "rgba(255,255,255,0.12)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = "rgba(255,255,255,0.06)";
              }}
            >
              Cerrar sesión
            </button>
          </div>
        )}
      </header>

      <div style={styles.body}>
        {/* Navegacion lateral */}
        <nav style={styles.sidebar}>
          <ul style={styles.navList}>
            {links.map(({ to, label, end }) => (
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
  topbarLeft: {
    display: "flex",
    alignItems: "center",
    gap: "10px",
    minWidth: 0,
  },
  brand: {
    fontWeight: 600,
    fontSize: "13px",
    letterSpacing: "0.02em",
    whiteSpace: "nowrap",
  },
  chip: {
    fontSize: "11px",
    background: "rgba(255,255,255,0.08)",
    padding: "2px 8px",
    borderRadius: "10px",
    color: "#a0aec0",
    whiteSpace: "nowrap",
  },
  userMenu: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    flexShrink: 0,
  },
  userIdentity: {
    display: "flex",
    alignItems: "center",
    gap: "5px",
    fontSize: "11px",
    padding: "3px 8px",
    borderRadius: "10px",
    background: "rgba(255,255,255,0.06)",
    whiteSpace: "nowrap",
  },
  userEmail: {
    color: "#e2e8f0",
  },
  userRoleDot: {
    color: "#5a5f78",
  },
  userRole: {
    color: "#8fb3e8",
    fontWeight: 600,
    textTransform: "uppercase",
    letterSpacing: "0.04em",
    fontSize: "10px",
  },
  logoutButton: {
    fontSize: "11px",
    fontFamily: "inherit",
    color: "#e2e8f0",
    background: "rgba(255,255,255,0.06)",
    border: "1px solid rgba(255,255,255,0.14)",
    borderRadius: "6px",
    padding: "3px 9px",
    cursor: "pointer",
    whiteSpace: "nowrap",
    transition: "background 120ms ease",
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
