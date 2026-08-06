import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { FileSpreadsheet, Layers, Package, ScrollText, Users } from "lucide-react";
import { getStatus } from "@/api/corridas";
import { getPresencia } from "@/api/presencia";
import type { StatusResponse, UsuarioEnLinea } from "@/lib/tipos";
import { useAuth } from "@/lib/auth";
import { puede } from "@/components/rutas";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Una lectura del estado: etiqueta arriba, valor en mono abajo.
 *
 *  Antes las tres iban en una sola cadena interpolada ("7095 insumos · 1204 APUs ·
 *  IA: fallback") y para sacar un número había que leerla entera. */
function Lectura({ etiqueta, children }: { etiqueta: string; children: React.ReactNode }) {
  return (
    <span className="flex flex-col justify-center gap-px px-3.5 leading-tight border-l border-hairline first:border-l-0 first:pl-0">
      <span className="text-[9px] font-medium uppercase tracking-[0.1em] text-muted-foreground">
        {etiqueta}
      </span>
      <span className="font-mono text-xs font-medium text-foreground">{children}</span>
    </span>
  );
}

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

  const [enLinea, setEnLinea] = useState<UsuarioEnLinea[] | null>(null);

  // Presencia: un poll de 45 s contra una ventana de 90 s en el servidor (dos latidos
  // de margen, así una petición perdida no apaga el punto). El poll ES el latido.
  useEffect(() => {
    let vivo = true;
    const pedir = () => {
      // Una pestaña de fondo no está "usando" la app: deja de latir y a los 90 s
      // desaparece de la lista de los demás.
      if (document.hidden) return;
      getPresencia()
        .then((r) => {
          if (vivo) setEnLinea(r.en_linea);
        })
        .catch(() => {
          /* sin backend — silencioso, se conserva la última lista */
        });
    };
    pedir();
    const t = setInterval(pedir, 45_000);
    // Volver a la pestaña no espera el resto del intervalo: sin esto, la lectura
    // queda desactualizada hasta 45 s (y los demás no te vieron hasta 90 s).
    document.addEventListener("visibilitychange", pedir);
    return () => {
      vivo = false;
      clearInterval(t);
      document.removeEventListener("visibilitychange", pedir);
    };
  }, []);

  // Mientras carga, un guion por lectura. Antes decía "cargando…" en el chip entero.
  const num = (n: number | undefined) => (n === undefined ? "—" : n.toLocaleString("es-CO"));

  // Los nombres en el title: la barra es densa y no caben dos columnas de gente.
  const quienes = (enLinea ?? [])
    .map((u) => `${u.nombre || u.email}${u.email === perfil?.email ? " (vos)" : ""}`)
    .join("\n");

  const esAdmin = puede(perfil?.rol, "admin");
  // `admin` marca el grupo, en vez de deducirlo de la posición: con un `i === 3` el
  // separador se corría de lugar en silencio en cuanto alguien agregara una sección.
  const links = [
    { to: "/corridas", label: "Corridas", end: false, Icono: Layers, admin: false },
    { to: "/insumos", label: "Insumos", end: true, Icono: Package, admin: false },
    { to: "/apus", label: "APUs", end: true, Icono: FileSpreadsheet, admin: false },
    ...(esAdmin
      ? [
          { to: "/usuarios", label: "Usuarios", end: true, Icono: Users, admin: true },
          { to: "/auditoria", label: "Auditoría", end: true, Icono: ScrollText, admin: true },
        ]
      : []),
  ];

  return (
    <div className="flex min-h-dvh flex-col text-[13px]">
      {/* La barra. `@container` para que las piezas cedan según el ancho que la barra
          tiene de verdad, no el del viewport. */}
      <header className="@container shrink-0 border-b border-border bg-card">
        <div className="flex h-[54px] items-stretch justify-between gap-5 px-[18px]">
          <div className="flex min-w-0 items-stretch gap-1 @max-[700px]:overflow-x-auto">
            <span className="flex shrink-0 items-center gap-2.5 pr-3.5 whitespace-nowrap">
              <svg
                viewBox="0 0 16 16"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinecap="round"
                aria-hidden
                className="size-4 shrink-0 text-rail"
              >
                <path d="M2 4h12" />
                <path d="M2 8h8" />
                <path d="M2 12h4" />
              </svg>
              <span className="text-sm font-semibold tracking-[-0.015em] @max-[700px]:hidden">
                Armador de APUs
              </span>
            </span>

            <nav aria-label="Secciones" className="flex items-stretch">
              {links.map(({ to, label, end, Icono, admin }, i) => (
                <span key={to} className="flex items-stretch">
                  {/* Los de administración van detrás de un separador: no son parte
                      del trabajo diario y conviene que se lean como otro grupo. Se
                      dibuja en el primero del grupo, sea cual sea su posición. */}
                  {admin && !links[i - 1]?.admin && (
                    <span aria-hidden className="my-4 w-px shrink-0 bg-hairline" />
                  )}
                  <NavLink
                    to={to}
                    end={end}
                    className={({ isActive }) =>
                      cn(
                        "flex items-center gap-2 whitespace-nowrap border-b-2 px-3 -mb-px no-underline",
                        "hover:text-foreground [&>svg]:hover:opacity-100",
                        isActive
                          ? "border-rail font-semibold text-foreground [&>svg]:text-rail [&>svg]:opacity-100"
                          : "border-transparent text-muted-foreground",
                      )
                    }
                  >
                    <Icono aria-hidden className="size-3.5 shrink-0 opacity-75" />
                    {label}
                  </NavLink>
                </span>
              ))}
            </nav>
          </div>

          {perfil && (
            <div className="flex shrink-0 items-center gap-3.5">
              {/* Orden de sacrificio al angostarse: primero el correo (decorativo),
                  después estas lecturas (informativas), al final el nombre de la marca.
                  La navegación no se oculta nunca. */}
              <div className="flex items-stretch @max-[980px]:hidden">
                <Lectura etiqueta="En línea">
                  <span className="flex items-center gap-1.5" title={quienes}>
                    <span
                      aria-hidden
                      className="size-[5px] shrink-0 rounded-full bg-margen-pos"
                    />
                    {enLinea ? enLinea.length : "—"}
                  </span>
                </Lectura>
                <Lectura etiqueta="Insumos">{num(status?.insumos)}</Lectura>
                <Lectura etiqueta="APUs">{num(status?.apus)}</Lectura>
                <Lectura etiqueta="IA">
                  <span className="flex items-center gap-1.5">
                    <span
                      aria-hidden
                      className={cn(
                        "size-[5px] shrink-0 rounded-full",
                        status?.ia ? "bg-margen-pos" : "bg-muted-foreground/55",
                      )}
                    />
                    {status ? (status.ia ? "habilitada" : "fallback") : "—"}
                  </span>
                </Lectura>
              </div>

              <span className="flex items-center gap-2 whitespace-nowrap text-xs text-muted-foreground">
                <span className="@max-[1180px]:hidden">{perfil.email}</span>
                <span className="font-mono text-[9px] font-semibold uppercase tracking-[0.1em] text-rail">
                  {perfil.rol}
                </span>
              </span>

              <Button variant="ghost" size="xs" onClick={() => logout()}>
                Cerrar sesión
              </Button>
            </div>
          )}
        </div>
      </header>

      <main className="min-w-0 flex-1 overflow-auto bg-background">
        <Outlet />
      </main>
    </div>
  );
}
