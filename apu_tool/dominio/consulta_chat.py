"""Chat de consulta: preguntas de precios y totales sin que la IA vea dinero.

La IA entiende la pregunta y busca con herramientas que devuelven nombres y `ref`,
sin un monto. Redacta con MARCADORES (`{{costo:corrida:12}}`) y las cifras las pone
`servicio/consulta.py` cuando el modelo ya terminó. Spec:
docs/superpowers/specs/2026-11-25-chat-consulta-design.md

Dos piezas, como en `composicion_chat.py`:
  - `HerramientasConsulta`: búsquedas de solo lectura; todo sale por helpers de
    `privacy` (campo por campo, sin dinero).
  - `conversar`: el bucle de tool use, como generador de eventos SSE.
"""
from __future__ import annotations

import logging
import re

from apu_tool.datos.almacen import Almacen
from apu_tool.dominio import privacy
from apu_tool.dominio.ai_assist import (  # noqa: F401  (re-export: servicio/ no importa la fachada de la IA)
    PROMPT_VERSION_CONSULTA, ApuAdvisor, IANoDisponible,
)
from apu_tool.dominio.composicion_chat import (
    _MAX_VUELTAS, MAX_HERRAMIENTAS, MAX_RESULTADOS_APUS, MAX_RESULTADOS_INSUMOS,
    MIN_RESULTADOS_SIN_SUGERENCIA, MSG_OMITIDO, MSG_REINTENTAR, SUGERENCIA_POCOS,
    _acotar,
)
from apu_tool.dominio.matching import Matcher
from apu_tool.nucleo.relevancia import _tokens
from apu_tool.nucleo.texto import normalizar

logger = logging.getLogger(__name__)

TURNOS = ("DIURNO", "NOCTURNO")
MAX_PROYECTOS = 5
MAX_CORRIDAS = 10


def _terminos(texto: str) -> list[str]:
    """Las palabras que sirven para buscar un proyecto: de 3 letras o más, o números
    («13» de «calle 13»). «la», «de» no filtran nada."""
    return [t for t in normalizar(texto).split() if len(t) >= 3 or t.isdigit()]


def _casa(terminos: list[str], nombre: str) -> bool:
    n = normalizar(nombre or "")
    return bool(terminos) and all(t in n for t in terminos)


def _nombre_corrida(meta) -> str:
    return meta.nombre or str(meta.archivo).rsplit(".", 1)[0]


class HerramientasConsulta:
    """Una instancia por mensaje: el `Matcher` se arma la primera vez y se reusa."""

    def __init__(self, almacen: Almacen):
        self.alm = almacen
        self._matcher = None
        # Nombres que salieron en resultados de ESTE mensaje. `conversar` los quita del
        # texto del modelo antes de buscar cifras inventadas: 54 nombres reales del
        # catálogo («PESO 60.000 KG») dispararían el detector, y no son montos.
        self.nombres: set[str] = set()

    def ejecutar(self, nombre: str, entrada: dict) -> dict:
        entrada = entrada if isinstance(entrada, dict) else {}
        texto = str(entrada.get("texto", "") or "")[:200]
        if nombre == "buscar_insumos":
            return self.buscar_insumos(texto)
        if nombre == "buscar_apus":
            return self.buscar_apus(texto)
        if nombre == "buscar_proyectos":
            return self.buscar_proyectos(texto)
        if nombre == "capitulos":
            return self.capitulos(entrada.get("corrida_id"))
        return {"error": f"Herramienta desconocida: {nombre}"}

    def buscar_insumos(self, texto: str) -> dict:
        if not [t for t in _tokens(texto) if len(t) >= 3]:
            return {"consulta": texto, "encontrados": 0, "insumos": []}
        # La búsqueda del buscador de la mesa (AND de palabras, sin ocultos, rankeada),
        # NO `search_insumos_por_palabras` (OR con LIMIT 60 sin orden, y N+1).
        ordenados, n = self.alm.precios.list_insumos(texto, limit=MAX_RESULTADOS_INSUMOS)
        # `encontrados` y no `total`: `total` está en `_FORBIDDEN_KEYS`.
        out = {"consulta": texto, "encontrados": n,
               "insumos": [privacy.insumo_consulta_to_dict(i) for i in ordenados]}
        self.nombres.update(i.nombre for i in ordenados)
        if n < MIN_RESULTADOS_SIN_SUGERENCIA:
            out["sugerencia"] = SUGERENCIA_POCOS
        return out

    def buscar_apus(self, texto: str) -> dict:
        if self._matcher is None:
            self._matcher = Matcher(self.alm.apus.apu_index())
        apus, vistos = [], set()
        for turno in TURNOS:
            for c in self._matcher.candidates(texto, turno, top_n=MAX_RESULTADOS_APUS):
                # ponytail: sin APUs de un turno, el `Matcher` cae a los del otro y el
                # turno de la etiqueta queda mal; el marcador sale «no disponible»
                # (cost_apu no encuentra composición), no con otra cifra. Techo aceptado.
                if (c.apu_codigo, turno) in vistos:
                    continue
                vistos.add((c.apu_codigo, turno))
                self.nombres.add(c.apu_nombre)
                apus.append(privacy.apu_consulta_to_dict(c.apu_codigo, c.apu_nombre,
                                                         turno))
        return {"consulta": texto, "apus": apus}

    def buscar_proyectos(self, texto: str) -> dict:
        terminos = _terminos(texto)
        vacio = {"consulta": texto, "proyectos": [], "corridas": []}
        if not terminos:
            return vacio
        carpetas = {c.id: c for c in self.alm.carpetas.listar()}

        def proyecto_de(carpeta_id):
            c = carpetas.get(carpeta_id)
            if c is None:
                return None
            return carpetas.get(c.parent_id) if c.parent_id else c

        def dto(meta):
            c = carpetas.get(meta.carpeta_id)
            return privacy.corrida_consulta_to_dict(meta, c.nombre if c else None)

        corridas = self.alm.corridas.listar_corridas()
        proyectos = [c for c in carpetas.values()
                     if c.parent_id is None and _casa(terminos, c.nombre)]
        ids = {p.id for p in proyectos[:MAX_PROYECTOS]}
        salida = []
        for p in proyectos[:MAX_PROYECTOS]:
            suyas = [m for m in corridas
                     if (pr := proyecto_de(m.carpeta_id)) is not None and pr.id == p.id]
            salida.append(privacy.proyecto_consulta_to_dict(
                p.nombre, [dto(m) for m in suyas[:MAX_CORRIDAS]], len(suyas)))
        sueltas = [m for m in corridas
                   if _casa(terminos, _nombre_corrida(m))
                   and getattr(proyecto_de(m.carpeta_id), "id", None) not in ids]
        return {"consulta": texto, "proyectos": salida,
                "proyectos_encontrados": len(proyectos),
                "corridas": [dto(m) for m in sueltas[:MAX_CORRIDAS]],
                "corridas_encontradas": len(sueltas)}

    def capitulos(self, corrida_id) -> dict:
        try:
            cid = int(corrida_id)
        except (TypeError, ValueError):
            return {"error": "corrida_id tiene que ser el número del ref 'corrida:N'."}
        if self.alm.corridas.get_corrida(cid) is None:
            return {"error": f"No existe la corrida {cid}."}
        # Se cuentan desde las filas, SIN costear: `vista_corrida` vive en `servicio/`
        # y para nombrar capítulos no hace falta dinero.
        caps: dict[str, dict] = {}
        for r in self.alm.corridas.get_items(cid):
            cod = r.item.capitulo_codigo
            if not cod:
                continue
            c = caps.setdefault(cod, {"nombre": r.item.capitulo_nombre or "", "n": 0})
            c["n"] += 1
        self.nombres.update(c["nombre"] for c in caps.values())
        return {"corrida_id": cid,
                "capitulos": [privacy.capitulo_consulta_to_dict(cid, cod, c["nombre"],
                                                                c["n"])
                              for cod, c in caps.items()]}


# ----------------------------------------------------------------- marcadores
# `{{<campo>:<tipo>:<id>}}`. El id de un capítulo lleva ":" adentro (`12:2`) y el de
# un APU lleva "|" (`4859|DIURNO`): por eso el id es "todo hasta las llaves".
MARCADOR = re.compile(
    r"\{\{\s*(precio|costo|contractual|diferencia|margen)\s*:\s*"
    r"(insumo|apu|corrida|capitulo)\s*:\s*([^{}]+?)\s*\}\}", re.IGNORECASE)
MSG_CIFRA_OMITIDA = "[se omitió una cifra que no vino del sistema]"
# Un porcentaje en el historial "del agente" es un margen resuelto (margen_pct está en
# `_FORBIDDEN_KEYS`): si un cliente manda el `texto` en vez del `crudo`, se omite.
_PORCENTAJE = re.compile(r"\d\s*%")


def sin_marcadores(texto: str) -> str:
    """El texto con cada marcador reducido a su ID. El id queda A LA VISTA del
    detector a propósito: si se borrara el marcador entero, `{{x:y:vale $45.000}}`
    sería un hueco para pasarle montos al modelo (el texto viaja intacto)."""
    return MARCADOR.sub(lambda m: f" {m.group(3)} ", texto or "")


def limpiar_cifras_inventadas(texto: str, conocidos=()) -> str:
    """Reemplaza cada LÍNEA que trae una cifra escrita por el modelo: no tenía de
    dónde sacarla, así que la inventó. Por línea y no por párrafo: una lista con «- »
    es un solo párrafo.

    `conocidos` son los nombres que devolvieron las herramientas en este mensaje: se
    quitan (sin importar mayúsculas) ANTES de buscar cifras, porque 54 nombres reales
    del catálogo («BASCULA PESO 60.000 KG») disparan el detector y no son montos. Son
    datos del catálogo, no del modelo: quitarlos no abre ningún hueco."""
    # Solo los nombres que disparan el detector: un capítulo «0» borraría todos los ceros.
    patrones = [re.compile(re.escape(n), re.IGNORECASE)
                for n in sorted({n for n in conocidos
                                 if n and privacy.cifra_monetaria(n)},
                                key=len, reverse=True)]

    def visible(linea: str) -> str:
        v = sin_marcadores(linea)
        for p in patrones:
            v = p.sub(" ", v)
        return v

    return "\n".join(
        MSG_CIFRA_OMITIDA if privacy.cifra_monetaria(visible(p)) else p
        for p in (texto or "").split("\n"))


# ----------------------------------------------------------------------- bucle
def _registrar_uso(resp, usadas: int) -> None:
    uso = getattr(resp, "usage", None)
    logger.info("chat consulta: entrada=%s salida=%s búsquedas=%s",
                getattr(uso, "input_tokens", "?"), getattr(uso, "output_tokens", "?"),
                usadas)


def _consulta(nombre: str, entrada: dict) -> str:
    if nombre == "capitulos":
        return f"corrida {entrada.get('corrida_id', '')}"
    texto = str(entrada.get("texto", ""))[:200]
    return "…" if privacy.cifra_monetaria(texto) else texto


def conversar(almacen: Almacen, mensajes: list, advisor):
    """Responde el último mensaje. Generador de eventos SSE:

      ('bloqueado', {'motivo'})       el mensaje del usuario trae dinero
      ('pensando',  {})
      ('buscando',  {'herramienta', 'consulta'})
      ('respuesta', {crudo, modelo, prompt_version})   crudo = texto CON marcadores
      ('error',     {'detail'})

    Las cifras NO las pone esto: `servicio/consulta.py` reemplaza los marcadores del
    `crudo` cuando el modelo ya terminó. Una `PrivacyViolation` sube, como en la mesa.

    ponytail: el bucle es copia del de `composicion_chat.conversar` (unas 40 líneas).
    Extraerlo tocaría el chat de la mesa, en producción, y las dos respuestas finales
    no se parecen. Si aparece un tercer chat, ahí se extrae.
    """
    mensajes = _acotar(mensajes)
    if not mensajes or mensajes[-1]["rol"] != "usuario":
        yield ("error", {"detail": "No hay un mensaje tuyo que responder."})
        return
    # El historial lo manda el cliente. Usuario: detector COMPLETO, bloquea (la
    # persona reescribe). Agente: solo señales fuertes y se OMITE (bloquear envenenaría
    # el chat). Los marcadores no cuentan en ninguno de los dos: son referencias.
    for m in mensajes:
        if m["rol"] == "usuario":
            # Crudo: una persona no escribe marcadores.
            motivo = privacy.texto_con_dinero(m["texto"])
            if not motivo and _PORCENTAJE.search(m["texto"]):
                motivo = ("El mensaje trae un porcentaje. La IA no puede ver márgenes: "
                          "quítalo y vuelve a enviarlo.")
            if motivo:
                yield ("bloqueado", {"motivo": motivo})
                return
        else:
            # Por línea: un nombre del catálogo («PESO 60.000 KG») no tumba el mensaje.
            def dispara(linea):
                v = sin_marcadores(linea)
                return bool(privacy.cifra_monetaria(v) or _PORCENTAJE.search(v))
            lineas = m["texto"].split("\n")
            con_texto = [l for l in lineas if l.strip()]
            if con_texto and all(dispara(l) for l in con_texto):
                m["texto"] = MSG_OMITIDO
            else:
                m["texto"] = "\n".join(MSG_CIFRA_OMITIDA if dispara(l) else l
                                       for l in lineas)

    api = [{"role": "user" if m["rol"] == "usuario" else "assistant",
            "content": m["texto"]} for m in mensajes]
    herramientas = HerramientasConsulta(almacen)
    usadas = 0
    yield ("pensando", {})
    try:
        for _ in range(_MAX_VUELTAS):
            resp = advisor.turno_consulta(api, con_herramientas=usadas < MAX_HERRAMIENTAS)
            _registrar_uso(resp, usadas)
            parada = getattr(resp, "stop_reason", None)
            if parada == "tool_use":
                # El contenido COMPLETO, con el pensamiento: la API lo exige de vuelta.
                api.append({"role": "assistant", "content": resp.content})
                resultados = []
                for b in resp.content:
                    if getattr(b, "type", None) != "tool_use":
                        continue
                    usadas += 1
                    entrada = b.input if isinstance(b.input, dict) else {}
                    yield ("buscando", {"herramienta": b.name,
                                        "consulta": _consulta(b.name, entrada)})
                    if usadas > MAX_HERRAMIENTAS:
                        resultados.append({
                            "type": "tool_result", "tool_use_id": b.id,
                            "is_error": True,
                            "content": "Llegaste al tope de búsquedas de este "
                                       "mensaje: responde con lo que ya tienes."})
                    else:
                        resultados.append({
                            "type": "tool_result", "tool_use_id": b.id,
                            "content": privacy.safe_json(
                                herramientas.ejecutar(b.name, entrada))})
                if not resultados:
                    yield ("error", {"detail": MSG_REINTENTAR})
                    return
                api.append({"role": "user", "content": resultados})
                yield ("pensando", {})
                continue
            if parada == "refusal":
                yield ("error", {"detail": "La IA no quiso responder ese mensaje. "
                                           "Reformúlalo."})
                return
            if parada == "max_tokens":
                yield ("error", {"detail": "La respuesta se cortó por longitud. "
                                           "Pregunta algo más puntual."})
                return
            texto = "\n\n".join(b.text for b in resp.content
                                if getattr(b, "type", None) == "text").strip()
            if not texto:
                yield ("error", {"detail": MSG_REINTENTAR})
                return
            yield ("respuesta", {"crudo": limpiar_cifras_inventadas(
                                     texto, herramientas.nombres),
                                 "modelo": advisor.model,
                                 "prompt_version": PROMPT_VERSION_CONSULTA})
            return
        yield ("error", {"detail": MSG_REINTENTAR})
    except privacy.PrivacyViolation:
        raise                                   # el invariante #1 nunca se traga
    except IANoDisponible as exc:
        yield ("error", {"detail": str(exc)})
    except Exception:
        logger.exception("Falló una vuelta del chat de consulta")
        yield ("error", {"detail": MSG_REINTENTAR})
