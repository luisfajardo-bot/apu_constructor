import "./AvatarIngeniero.css";

export type EstadoAvatar =
  | "espera" | "pensando" | "buscando" | "lista" | "error" | "deshabilitado";

const ETIQUETA: Record<EstadoAvatar, string> = {
  espera: "El agente está esperando tu mensaje",
  pensando: "El agente está pensando",
  buscando: "El agente está buscando en el catálogo",
  lista: "El agente tiene una propuesta lista",
  error: "El agente no pudo responder",
  deshabilitado: "El agente no está disponible",
};

/** Ingeniero de cabeza y hombros con casco. El estado sale del SSE del chat y cada
 *  uno tiene su gesto (ver AvatarIngeniero.css). SVG inline y CSS puro: nada que
 *  descargar. Con `prefers-reduced-motion` no se mueve; solo cambia de color. */
export default function AvatarIngeniero({
  estado,
  tamano = 48,
}: {
  estado: EstadoAvatar;
  tamano?: number;
}) {
  return (
    <svg
      className="avatar-ing"
      data-estado={estado}
      role="img"
      aria-label={ETIQUETA[estado]}
      width={tamano}
      height={tamano}
      viewBox="0 0 64 64"
    >
      <g className="av-cuerpo">
        {/* hombros con chaleco y franja reflectiva */}
        <path className="av-chaleco" d="M10 64 C10 51 19 45 32 45 C45 45 54 51 54 64 Z" />
        <rect className="av-franja" x="13" y="55" width="38" height="3" rx="1" />
        <rect className="av-piel" x="28" y="38" width="8" height="8" rx="2" />
      </g>
      <g className="av-cabeza">
        <circle className="av-piel" cx="32" cy="29" r="11.5" />
        <g className="av-ojos">
          <circle cx="27.6" cy="30" r="1.6" />
          <circle cx="36.4" cy="30" r="1.6" />
        </g>
        <path className="av-boca" d="M28.5 35 Q32 37.5 35.5 35" />
        {/* casco: domo, cresta y ala */}
        <path className="av-casco" d="M19.5 26 C19.5 15 25.5 11 32 11 C38.5 11 44.5 15 44.5 26 Z" />
        <rect className="av-casco-cresta" x="30.5" y="11.5" width="3" height="13" rx="1.5" />
        <rect className="av-casco" x="16.5" y="24.5" width="31" height="3.5" rx="1.75" />
      </g>
      {/* pensando: mano en la barbilla */}
      <g className="av-mano-barbilla">
        {/* Antebrazo que sube del pecho a la barbilla. Arranca DENTRO del chaleco:
            un trazo diagonal desde el hombro se leía como una banda (verificado en el
            navegador). */}
        <path className="av-manga" d="M39.5 60 L37 46" />
        <circle className="av-piel av-mano" cx="36.4" cy="43" r="3.6" />
      </g>
      {/* lista: un visto bueno al lado. Era un pulgar arriba, pero dibujado con dos
          rectángulos se leía como otro dedo (verificado en el navegador). */}
      <g className="av-visto">
        <circle cx="50" cy="40" r="7" />
        <path d="M46.6 40.2 L49 42.7 L53.6 37.7" />
      </g>
      {/* buscando: lupa */}
      <g className="av-lupa">
        <circle cx="50" cy="40" r="5.5" />
        <line x1="54" y1="44" x2="59" y2="49" />
      </g>
    </svg>
  );
}
