import { apiGet } from "./client";
import type { PresenciaResponse } from "@/lib/tipos";

/** Quién está usando la app ahora. Pedirla también te marca presente (el latido es
 *  este mismo poll, ver apu_tool/servicio/presencia.py). */
export function getPresencia(): Promise<PresenciaResponse> {
  return apiGet<PresenciaResponse>("/presencia");
}
