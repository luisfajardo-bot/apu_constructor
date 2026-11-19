"""Chat con el agente en la mesa de composición.

Hermano de `composicion_agente.py`: el agente busca en el catálogo y PROPONE cambios a
la composición de una fila; la persona los aplica (el `PUT` de la mesa) o los
descarta. Acá no se persiste nada.

Dos piezas:
  - `Herramientas`: las búsquedas que el modelo puede pedir. Solo lectura, y todo lo
    que devuelven pasa por los helpers de `privacy` (copia campo por campo, sin
    precio) antes de volver al modelo.
  - `conversar`: el bucle de tool use, como generador de eventos SSE.
"""
from __future__ import annotations

import json
import logging
from dataclasses import replace

from apu_tool.datos.almacen import Almacen
from apu_tool.dominio import cruce, privacy
from apu_tool.dominio.ai_assist import OPS_CHAT, PROMPT_VERSION_CHAT, IANoDisponible
from apu_tool.dominio.compose import rendimientos_observados
from apu_tool.dominio.composicion import propuesta_desde_json
from apu_tool.dominio.matching import Matcher
from apu_tool.nucleo.relevancia import _tokens

logger = logging.getLogger(__name__)

MAX_RESULTADOS_INSUMOS = 15
MIN_RESULTADOS_SIN_SUGERENCIA = 3
SUGERENCIA_POCOS = ("Pocos resultados: la búsqueda exige todas las palabras. Prueba "
                    "con menos palabras: quita adjetivos («sanitaria», «corrugada») y "
                    "deja lo esencial, con el diámetro como 12\".")
MAX_RESULTADOS_APUS = 5


class Herramientas:
    """Las búsquedas del agente. Una instancia por mensaje: el `Matcher` se arma la
    primera vez que se pide `buscar_apus` y se reusa en las siguientes."""

    def __init__(self, almacen: Almacen, shift: str):
        self.alm = almacen
        self.shift = shift
        self._matcher = None

    def ejecutar(self, nombre: str, entrada: dict) -> dict:
        texto = str((entrada or {}).get("texto", "") or "")[:200]
        if nombre == "buscar_insumos":
            return self.buscar_insumos(texto)
        if nombre == "buscar_apus":
            return self.buscar_apus(texto)
        return {"error": f"Herramienta desconocida: {nombre}"}

    def buscar_insumos(self, texto: str) -> dict:
        if not [t for t in _tokens(texto) if len(t) >= 3]:
            return {"consulta": texto, "insumos": []}     # "de la": nada que buscar
        # La misma búsqueda del `BuscadorInsumo` de la mesa: AND de palabras, sin
        # ocultos, rankeada por relevancia, 2 consultas. NO `search_insumos_por_palabras`:
        # hace OR con LIMIT 60 sin orden ("tuberia pvc" casa 1451 insumos en el
        # catálogo real y se rankeaban 60 al azar) y es N+1.
        ordenados, total = self.alm.precios.list_insumos(
            texto, limit=MAX_RESULTADOS_INSUMOS)
        obs = rendimientos_observados(self.alm, [i.codigo for i in ordenados])
        out = {"consulta": texto, "encontrados": total,
               "insumos": [privacy.insumo_encontrado_to_dict(i, obs.get(i.codigo))
                           for i in ordenados]}
        # `encontrados` y no `total`: `total` está en `_FORBIDDEN_KEYS` (es dinero en
        # este repo) y `assert_no_money` volaría el payload — lo atajó un test.
        # La búsqueda exige TODAS las palabras. En el smoke real «tuberia pvc
        # sanitaria 12» dejó afuera los tubos de 12" que sí estaban (por «sanitaria»)
        # y el agente no reformuló. Con pocos resultados se lo decimos explícito.
        if total < MIN_RESULTADOS_SIN_SUGERENCIA:
            out["sugerencia"] = SUGERENCIA_POCOS
        return out

    def buscar_apus(self, texto: str) -> dict:
        if self._matcher is None:
            self._matcher = Matcher(self.alm.apus.apu_index())
        apus = []
        # ponytail: sin APUs del turno pedido el `Matcher` cae a todos los turnos, pero
        # `MatchCandidate` no trae el turno del candidato y acá se pide el turno original:
        # el APU de otro turno no se devuelve. Techo aceptado (la biblioteca real tiene
        # ambos turnos); si molesta, `candidates` tendría que devolver el turno.
        for c in self._matcher.candidates(texto, self.shift,
                                          top_n=MAX_RESULTADOS_APUS):
            dp = self.alm.apus.get_depriced_apu(c.apu_codigo, self.shift)
            if dp is not None:
                apus.append(privacy.depriced_apu_to_dict(dp))
        return {"consulta": texto, "apus": apus}


# ----------------------------------------------------------------------- bucle
MAX_HERRAMIENTAS = 4           # búsquedas por mensaje
MAX_MENSAJES = 20              # historial que viaja al modelo
MAX_TEXTO_MENSAJE = 1000
# Vueltas del bucle: las de herramientas, más la que ya no puede buscar, más una de
# holgura. Un modelo que sigue pidiendo herramientas con `tool_choice: none` no
# debería existir; si existe, esto corta en vez de girar para siempre.
_MAX_VUELTAS = MAX_HERRAMIENTAS + 2
MSG_REINTENTAR = "No pude responder, vuelve a intentar."
MSG_OMITIDO = "[mensaje omitido: traía cifras que la IA no puede ver]"


def _acotar(mensajes: list) -> list[dict]:
    """Los últimos `MAX_MENSAJES` mensajes legibles, recortados, empezando por uno
    del usuario (la API exige que el primer turno sea `user`)."""
    limpios = []
    for m in mensajes or []:
        if not isinstance(m, dict) or m.get("rol") not in ("usuario", "agente"):
            continue
        texto = str(m.get("texto", "") or "").strip()[:MAX_TEXTO_MENSAJE]
        if texto:
            limpios.append({"rol": m["rol"], "texto": texto})
    limpios = limpios[-MAX_MENSAJES:]
    while limpios and limpios[0]["rol"] != "usuario":
        limpios.pop(0)
    return limpios


def _catalogo(almacen: Almacen, componentes) -> dict[str, dict]:
    """Ficha (nombre, unidad, grupo y, si el código es compartido, opciones) de cada
    componente de la mesa, en UNA consulta. El nombre que manda el cliente solo se usa
    para ESCOGER la fila: lo que se muestra y viaja al agente es el del catálogo (el
    del cliente es texto libre y podría traer un monto)."""
    comps = [c for c in componentes if isinstance(c, dict) and c.get("codigo")]
    if not comps:
        return {}
    bulk = almacen.precios.get_candidatos_bulk(sorted({str(c["codigo"]) for c in comps}))
    out = {}
    for c in comps:
        cod = str(c["codigo"])
        if bulk.get(cod):
            out[cod] = cruce.ficha(bulk[cod], str(c.get("nombre", "") or ""))
    return out


def _mensajes_api(mensajes: list[dict], contexto: str) -> list[dict]:
    """El historial como turnos de la API. El estado de la mesa va SOLO en el último
    mensaje: es el de ahora, y repetirlo en cada turno sería pagar tokens por fotos
    viejas de la tabla."""
    api = [{"role": "user" if m["rol"] == "usuario" else "assistant",
            "content": m["texto"]} for m in mensajes[:-1]]
    api.append({"role": "user", "content": [
        {"type": "text",
         "text": "ESTADO ACTUAL DE LA MESA (actividad y composición):\n" + contexto},
        {"type": "text", "text": mensajes[-1]["texto"]},
    ]})
    return api


def _respuesta(almacen: Almacen, data, modelo: str, componentes=()) -> dict:
    """La respuesta final, con los cambios filtrados por la plataforma.

    Un `agregar` cuyo código no existe, o cuya fila está oculta, se DESCARTA antes de
    mostrarse, y se dice cuál y por qué: nunca se pierde en silencio. `modificar` sin
    componente también se descarta. `quitar` y `modificar` no se cruzan con el
    catálogo: el código ya está en la tabla, y si no está, `aplicarCambios` (web) lo
    reporta como conflicto.

    Código compartido por dos insumos: lo decide el NOMBRE (`cruce.elegir_fila`), igual
    que en el alta. Si el nombre no alcanza el componente entra sin nombre y la mesa le
    pide a la persona que escoja (`CODIGO_COMPARTIDO`); ya no se descarta. Un `modificar`
    cuyo nombre no resuelve hereda la fila que la mesa (`componentes`) ya tenía
    escogida: cambiar un rendimiento no puede borrarle la elección a la persona.
    """
    data = data if isinstance(data, dict) else {}
    crudos = [c for c in (data.get("cambios") or []) if isinstance(c, dict)]
    codigos = [str(c.get("codigo", "") or "").strip()[:40] for c in crudos]
    # UNA consulta por respuesta: `Insumo.oculto` trae la visibilidad, así que no hace
    # falta una consulta por código (el egress de Supabase ya fue un problema).
    validos = sorted({c for c in codigos if c})
    bulk = almacen.precios.get_candidatos_bulk(validos) if validos else {}
    catalogo: dict[str, dict] = {}
    # Nombre con el que la mesa tiene cada código. Solo sirve para ESCOGER la fila: lo
    # que se guarda es el del catálogo.
    en_mesa = {str(m.get("codigo", "")): str(m.get("nombre", "") or "")
               for m in componentes if isinstance(m, dict)}
    cambios, descartados = [], []
    for c, cod in zip(crudos, codigos):
        op = c.get("op")
        if op not in OPS_CHAT or not cod:
            descartados.append({"codigo": cod, "motivo": "Cambio ilegible."})
            continue
        cands = bulk.get(cod) or []
        nombre = str(c.get("nombre", "") or "")
        fila = cruce.elegir_fila(cands, nombre)
        if fila is None and op == "modificar":
            fila = cruce.elegir_fila(cands, en_mesa.get(cod, ""))
        if op == "agregar":
            if not cands or all(x.oculto for x in cands):
                descartados.append({"codigo": cod,
                                    "motivo": "No está en el catálogo (o está oculto)."})
                continue
            if fila is not None and fila.oculto:
                descartados.append({"codigo": cod,
                                    "motivo": f"«{fila.nombre[:60]}» está oculto en el "
                                              "catálogo."})
                continue
        if cands:
            catalogo[cod] = cruce.ficha(cands, fila.nombre if fila else nombre)
        comp = None
        if op != "quitar":
            p = propuesta_desde_json({"componentes": [c.get("componente")]})
            if not p.componentes:
                descartados.append({"codigo": cod,
                                    "motivo": "El agente no mandó el componente."})
                continue
            # El nombre que se guarda es el del CATÁLOGO (la fila que eligió el nombre
            # del agente), nunca el texto del agente. Si no resolvió, va vacío y la
            # mesa le pide a la persona que escoja (CODIGO_COMPARTIDO).
            comp = replace(p.componentes[0], codigo=cod,
                           nombre=fila.nombre if fila else "").to_dict()
        cambios.append({"op": op, "codigo": cod, "componente": comp})
    return {"texto": str(data.get("texto", "") or "")[:2000], "cambios": cambios,
            "descartados": descartados, "catalogo": catalogo, "modelo": modelo,
            "prompt_version": PROMPT_VERSION_CHAT}


def _registrar_uso(resp, usadas: int) -> None:
    uso = getattr(resp, "usage", None)
    logger.info("chat composición: entrada=%s salida=%s búsquedas=%s",
                getattr(uso, "input_tokens", "?"), getattr(uso, "output_tokens", "?"),
                usadas)


def conversar(almacen: Almacen, item, componentes: list, mensajes: list, advisor):
    """Responde el último mensaje del chat. Generador de eventos SSE:

      ('bloqueado', {'motivo'})                      el historial trae dinero
      ('pensando',  {})
      ('buscando',  {'herramienta', 'consulta'})
      ('respuesta', {texto, cambios, descartados, catalogo, modelo, prompt_version})
      ('error',     {'detail'})

    No persiste nada: aplicar es del usuario, por el `PUT` de la mesa.

    Una `PrivacyViolation` NO se convierte en `error`: sube, como en
    `composicion_agente.componer`. Cualquier otro fallo de la IA sí (429, timeout,
    respuesta rota): el chat es interactivo y la persona reintenta.
    """
    mensajes = _acotar(mensajes)
    if not mensajes or mensajes[-1]["rol"] != "usuario":
        yield ("error", {"detail": "No hay un mensaje tuyo que responder."})
        return
    # TODOS se revisan: el historial lo manda el cliente. Los del usuario BLOQUEAN
    # (la persona puede reescribir el suyo). Los "del agente" se REEMPLAZAN: bloquear
    # por ellos envenenaría el chat, porque la persona no tiene cómo sacarlos del hilo.
    # En los dos casos el texto con cifras no viaja.
    for m in mensajes:
        motivo = privacy.texto_con_dinero(m["texto"])
        if not motivo:
            continue
        if m["rol"] == "usuario":
            yield ("bloqueado", {"motivo": motivo})
            return
        m["texto"] = MSG_OMITIDO

    catalogo = _catalogo(almacen, componentes)
    contexto = privacy.safe_json(privacy.payload_chat(item, componentes, catalogo))
    api = _mensajes_api(mensajes, contexto)
    herramientas = Herramientas(almacen, item.shift)
    usadas = 0
    yield ("pensando", {})
    try:
        for _ in range(_MAX_VUELTAS):
            resp = advisor.turno_chat(api, con_herramientas=usadas < MAX_HERRAMIENTAS)
            _registrar_uso(resp, usadas)
            parada = getattr(resp, "stop_reason", None)
            if parada == "tool_use":
                # El contenido COMPLETO, con los bloques de pensamiento: la API los
                # exige de vuelta dentro de un mismo turno de herramientas.
                api.append({"role": "assistant", "content": resp.content})
                resultados = []
                for b in resp.content:
                    if getattr(b, "type", None) != "tool_use":
                        continue
                    usadas += 1
                    entrada = b.input if isinstance(b.input, dict) else {}
                    yield ("buscando", {"herramienta": b.name,
                                        "consulta": str(entrada.get("texto", ""))[:200]})
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
                api.append({"role": "user", "content": resultados})
                yield ("pensando", {})
                continue
            if parada == "refusal":
                yield ("error", {"detail": "La IA no quiso responder ese mensaje. "
                                           "Reformúlalo."})
                return
            if parada == "max_tokens":
                yield ("error", {"detail": "La respuesta se cortó por longitud. "
                                           "Vuelve a intentar con algo más puntual."})
                return
            texto = next((b.text for b in resp.content
                          if getattr(b, "type", None) == "text"), "")
            try:
                data = json.loads(texto)
            except ValueError:
                yield ("error", {"detail": MSG_REINTENTAR})
                return
            yield ("respuesta", _respuesta(almacen, data, advisor.model, componentes))
            return
        yield ("error", {"detail": MSG_REINTENTAR})
    except privacy.PrivacyViolation:
        raise                                   # el invariante #1 nunca se traga
    except IANoDisponible as exc:
        yield ("error", {"detail": str(exc)})
    except Exception:
        logger.exception("Falló una vuelta del chat de composición")
        yield ("error", {"detail": MSG_REINTENTAR})
