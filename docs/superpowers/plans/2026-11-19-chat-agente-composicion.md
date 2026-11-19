# Chat con el agente en la mesa de composición — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un panel de chat en la mesa de composición (`/corridas/:id/componer/:seq`) con un agente visible (avatar de ingeniero con casco, animado según lo que hace) que busca en el catálogo y PROPONE cambios a la composición; la persona los aplica o los descarta.

**Architecture:** Un endpoint SSE nuevo (`POST .../composicion/{seq}/chat`) corre un bucle manual de tool use (`dominio/composicion_chat.py`) con dos herramientas de solo lectura y des-monetizadas, tope de 4 búsquedas, y termina con una respuesta de salida estructurada `{texto, cambios}`. Nada se persiste en el chat: "Aplicar" reusa el `PUT` de la mesa (`guardar_edicion`) con un campo nuevo `instruccion` que deja rastro en el expediente (`motivo="chat: …"`, `prompt_version="chat/v1"`). Un detector de dinero en `dominio/privacy.py` bloquea los mensajes con montos antes de llamar a la IA.

**Tech Stack:** Python 3 / FastAPI / pytest; SDK `anthropic` 0.111 (`messages.create` con `tools` + `output_config.format` + `thinking adaptive`); React + TypeScript + Vite / vitest; SVG + CSS `@keyframes` para el avatar.

**Spec:** `docs/superpowers/specs/2026-11-18-chat-agente-composicion-design.md`

---

## Antes de empezar

- Rama: `feat/chat-agente-composicion` (ya existe; la spec está commiteada). **No** hacer push a master: master auto-despliega y el push necesita OK explícito del usuario.
- Comandos de verificación:
  - Backend: `python -m pytest tests/ -q`
  - Frontend: `cd web && npx vitest run` y `cd web && npm run build` (el build corre `tsc -b`; `tsc --noEmit` NO basta).
- Textos nuevos para el usuario: español de Colombia, **tuteando** (nada de voseo: "revisa", no "revisá").
- Ningún módulo de `apu_tool/servicio/` puede nombrar el módulo de la fachada del SDK (`tests/test_servicio_privacidad.py` busca el nombre como texto, incluso en comentarios). `servicio/` toma `ApuAdvisor` e `IANoDisponible` de `dominio/composicion_agente.py`, como ya hace, y `PROMPT_VERSION_CHAT` de `dominio/composicion_chat.py`.
- La API combina `tools` + `output_config.format` + `thinking: adaptive` en la misma llamada (verificado en la referencia del SDK: "Using Both Together"; structured outputs "works with extended thinking"). En el bucle se devuelve `response.content` completo (con los bloques de pensamiento). `tool_choice: {"type": "none"}` es válido en todos los modelos; el forzado (`any`/`tool`) da 400 en los nuevos y NO se usa.

## Decisiones de implementación que ajustan la spec

Estas tres se descubrieron leyendo el código; la Tarea 1 actualiza la spec para que no se contradigan:

1. **`buscar_insumos(texto)` sin `grupo`.** Los grupos del catálogo real son texto libre ("SUELDOS Y JORNALES", "REDES ACUEDUCTO"…); un filtro `grupo="mano de obra"` no casaría con nada y quemaría una de las 4 búsquedas. El grupo viaja en cada resultado.
2. **El detector revisa TODOS los mensajes del historial, también los del agente.** El historial lo manda el cliente; un mensaje "del agente" es tan poco confiable como uno del usuario.
3. **El `PUT` recibe solo `instruccion`.** `modelo` y `prompt_version` los pone el servidor (`config.AI_MODEL` y `PROMPT_VERSION_CHAT`): son etiquetas para el reporte de correcciones y no tiene sentido dejarlas en manos del cliente.

## Mapa de archivos

| Archivo | Qué |
|---|---|
| `apu_tool/dominio/privacy.py` (modificar) | `texto_con_dinero`, `payload_chat`, `componente_mesa_to_dict`, `insumo_encontrado_to_dict` |
| `apu_tool/dominio/ai_assist.py` (modificar) | `PROMPT_VERSION_CHAT`, `_SISTEMA_CHAT`, `_ESQUEMA_CHAT`, `HERRAMIENTAS_CHAT`, `ApuAdvisor.turno_chat` / `_pedir_chat_al_sdk` |
| `apu_tool/dominio/composicion_chat.py` (crear) | `Herramientas` (búsquedas) y `conversar` (el bucle, generador de eventos) |
| `apu_tool/servicio/composicion.py` (modificar) | `chat_stream`, `guardar_edicion` (instrucción + mesa vacía), `vista` (`ia_disponible`) |
| `apu_tool/servicio/esquemas.py` (modificar) | `MensajeChatIn`, `ChatComposicionIn`, `ComposicionEditarIn.instruccion` |
| `apu_tool/servicio/rutas.py` (modificar) | `POST /corridas/{cid}/composicion/{seq}/chat` |
| `tests/chat_falso.py` (crear) | `AdvisorGuion` + constructores de respuestas falsas del SDK |
| `tests/test_privacy_chat.py` (crear) | detector de dinero y payloads del chat |
| `tests/test_composicion_chat_advisor.py` (crear) | la llamada al SDK del chat |
| `tests/test_composicion_chat_motor.py` (crear) | herramientas y bucle |
| `tests/test_api_composicion_chat.py` (crear) | endpoint de chat y `PUT` con instrucción |
| `tests/test_api_composicion.py` (modificar) | la vista trae `ia_disponible` |
| `web/src/lib/tipos.ts` (modificar) | tipos del chat; `ia_disponible?` en la vista |
| `web/src/api/composicion.ts` (modificar) | `chatComposicionStream`; `guardarComposicion(..., instruccion?)` |
| `web/src/lib/cambiosAgente.ts` (+ `.test.ts`) (crear) | `aplicarCambios` puro |
| `web/src/components/composicion/AvatarIngeniero.tsx` + `.css` + `.test.tsx` (crear) | el avatar |
| `web/src/components/composicion/PanelAgente.tsx` + `.test.tsx` (crear) | el chat |
| `web/src/pages/Composicion.tsx` (modificar) | monta el panel y aplica los cambios |
| `web/src/pages/Composicion.test.tsx` (modificar) | mock del stream nuevo + flujo de aplicar |
| `CLAUDE.md`, `docs/pendientes-agente-composicion.md` (modificar) | documentar la feature y sus candados |

---

### Task 1: Ajustar la spec a las decisiones de implementación

**Files:**
- Modify: `docs/superpowers/specs/2026-11-18-chat-agente-composicion-design.md`

- [ ] **Step 1: Editar la spec**

Hacer estos cuatro reemplazos:

1. En la tabla de herramientas, cambiar la fila de `buscar_insumos(texto, grupo?)` por:
```
| `buscar_insumos(texto)` | hasta 15: código, nombre, unidad, grupo y rendimientos observados (`rendimientos_observados`). Sin ocultos. Sin filtro por grupo: los grupos del catálogo son texto libre ("SUELDOS Y JORNALES") y un filtro mal adivinado quemaría una búsqueda. |
```
2. En "Antes de llamar a la IA", punto 1, reemplazar "revisa **todos** los mensajes del usuario del historial, no solo el último: el historial lo manda el cliente y el cliente puede mentir." por "revisa **todos** los mensajes del historial —también los del agente— y no solo el último: el historial lo manda el cliente y el cliente puede mentir."
3. En "Aplicar: el `PUT` de siempre", reemplazar el párrafo que empieza "Tres campos opcionales" y sus dos viñetas por:
```
Un campo opcional nuevo en el body: `instruccion` → se guarda como
`motivo = "chat: <instrucción>"`. `modelo` (`config.AI_MODEL`) y `prompt_version`
(`"chat/v1"`) los pone el **servidor** cuando hay instrucción: son etiquetas del
reporte de correcciones y el cliente no las dicta.
```
4. En "Pruebas → Backend", la viñeta del detector: después de `"COP 1200")` agregar `, un monto escondido en un mensaje "del agente"`.

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-11-18-chat-agente-composicion-design.md
git commit -m "docs(composicion): ajustes de la spec del chat al plan

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Detector de dinero en texto libre (`privacy.texto_con_dinero`)

**Files:**
- Modify: `apu_tool/dominio/privacy.py`
- Test: `tests/test_privacy_chat.py` (crear)

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_privacy_chat.py`:

```python
"""La frontera de privacidad del chat: el texto libre que escribe una persona.

`assert_no_money` mira NOMBRES de clave, no valores. El chat es el primer payload hacia
la IA hecho de texto libre escrito por personas, así que necesita un detector propio
para los valores. Preferimos fallar a filtrar: un falso positivo cuesta reescribir el
mensaje; un falso negativo le muestra un precio a la IA.
"""
import json

import pytest

from apu_tool.dominio import privacy
from apu_tool.dominio.compose import RendimientoObservado
from apu_tool.dominio.privacy import texto_con_dinero
from apu_tool.nucleo.models import Insumo, LicitacionItem


@pytest.mark.parametrize("texto", [
    "el cemento nos salió en $45.000",
    "$ 12000",
    "nos lo cotizaron a 45000",
    "Cotización: 1.250.000 el m3",
    "vale 3 millones",
    "COP 1200 por unidad",
    "eso cuesta 3000",
    "el precio es 12.500",
    "45 USD",
    "son 200 pesos",
    "valor 80.000",
])
def test_bloquea_un_monto(texto):
    motivo = texto_con_dinero(texto)
    assert motivo is not None
    assert "IA no puede ver precios" in motivo


@pytest.mark.parametrize("texto", [
    "8 horas por jornada",
    "rendimiento de 0,125 HH/m3",
    "1,05 m3 de concreto",
    "rendimiento de 12 m2 por jornada",
    "vale, agrega 2 ayudantes",
    "busca una mano de obra que tenga licencia de soldador",
    "el valor del rendimiento no me cuadra",
    "cuadrilla de 1 oficial y 2 ayudantes",
    "peso específico 2,4 t/m3",
    "",
])
def test_deja_pasar_cantidades_fisicas(texto):
    assert texto_con_dinero(texto) is None


def test_el_motivo_cita_el_fragmento_para_que_la_persona_lo_encuentre():
    motivo = texto_con_dinero("agrega el oficial, nos cobra 90.000 de tarifa diaria")
    assert "tarifa" in motivo or "cobra" in motivo
```

- [ ] **Step 2: Correr y ver que fallan**

Run: `python -m pytest tests/test_privacy_chat.py -q`
Expected: FAIL con `ImportError: cannot import name 'texto_con_dinero'`

- [ ] **Step 3: Implementar**

En `apu_tool/dominio/privacy.py`: agregar `import math` e `import re` a los imports y cambiar `from typing import Any` por `from typing import Any, Optional`. Después de `safe_json`, agregar:

```python
# --------------------------------------------------- texto libre (chat del agente)
# `assert_no_money` mira NOMBRES de clave. El chat de la mesa de composición es el
# primer payload hacia la IA armado con texto libre escrito por personas, así que los
# VALORES necesitan su propio detector. Preferimos fallar a filtrar: un falso positivo
# cuesta reescribir el mensaje; un falso negativo le muestra un precio a la IA.
#
# Lo que NO está, a propósito:
#   - "vale": en Colombia es "de acuerdo" ("vale, agrega 2 ayudantes"); "vale 3
#     millones" igual cae por "millones".
#   - "peso" en singular: es también peso físico ("peso específico 2,4 t/m3").
_SENAL_MONEDA = re.compile(r"\$|\b(cop|usd|pesos|d[oó]lares?)\b", re.IGNORECASE)
_RAIZ_DINERO = re.compile(
    r"(precios?|costos?|costar|cuesta|cuestan|valor(es)?|tarifas?|cotiz\w*|"
    r"presupuest\w*|mill[oó]n|millones|plata|cobra\w*)", re.IGNORECASE)
_VENTANA_DINERO = 3        # palabras a cada lado de la raíz donde se busca un número


def _motivo_dinero(fragmento: str) -> str:
    frag = fragmento.strip()[:60]
    return (f"El mensaje parece traer un monto («{frag}»). La IA no puede ver "
            "precios: quítalo y vuelve a enviarlo.")


def texto_con_dinero(texto: str) -> Optional[str]:
    """El motivo para bloquear `texto` si parece traer dinero, o None si no.

    Bloquea si hay un símbolo o una moneda (`$`, COP, USD, pesos, dólares) en
    cualquier parte, o una palabra de dinero (precio, costo, valor, tarifa, cotiz-,
    millones…) con un número a menos de `_VENTANA_DINERO` palabras. Deja pasar las
    cantidades físicas ("8 horas", "0,125 HH/m3"): sin palabra de dinero cerca, un
    número es un rendimiento.
    """
    t = texto or ""
    m = _SENAL_MONEDA.search(t)
    if m:
        ini = max(0, m.start() - 20)
        return _motivo_dinero(t[ini:m.end() + 20])
    tokens = [re.sub(r"^\W+|\W+$", "", p) for p in t.split()]
    for i, tok in enumerate(tokens):
        if not _RAIZ_DINERO.fullmatch(tok):
            continue
        vecinos = tokens[max(0, i - _VENTANA_DINERO): i + _VENTANA_DINERO + 1]
        if any(ch.isdigit() for v in vecinos for ch in v):
            return _motivo_dinero(" ".join(vecinos))
    return None
```

- [ ] **Step 4: Correr y ver que pasan**

Run: `python -m pytest tests/test_privacy_chat.py -q`
Expected: PASS (todos)

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/privacy.py tests/test_privacy_chat.py
git commit -m "feat(privacy): detector de montos en texto libre para el chat

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Payloads des-monetizados del chat

**Files:**
- Modify: `apu_tool/dominio/privacy.py`
- Test: `tests/test_privacy_chat.py`

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `tests/test_privacy_chat.py`:

```python
ITEM = LicitacionItem("1.3", "EXCAVACION MANUAL", "M3", 120.0, 180000.0, "DIURNO")
CATALOGO = {"4279": {"nombre": "CUADRILLA", "unidad": "HR", "grupo": "MO"}}
COMP = {"codigo": "4279", "tipo": "insumo", "funcion": "mano_de_obra",
        "rendimiento": 0.62, "origen": "copiado_de_antecedente",
        "referencias": [], "hipotesis": {"costo_m3": "45000"}, "calculo": None,
        "justificacion": "nos lo cobran a $45.000", "nivel_evidencia": "alto",
        "ref_shift": ""}


def test_payload_chat_no_lleva_dinero_ni_texto_libre_de_la_mesa():
    p = privacy.payload_chat(ITEM, [COMP], CATALOGO)
    privacy.assert_no_money(p)
    texto = json.dumps(p, ensure_ascii=False)
    assert "180000" not in texto          # precio_contractual
    assert "45000" not in texto           # hipotesis y justificacion: no viajan
    assert p["composicion_actual"] == [{
        "codigo": "4279", "nombre": "CUADRILLA", "unidad": "HR",
        "funcion": "mano_de_obra", "rendimiento": 0.62,
        "origen": "copiado_de_antecedente"}]


def test_un_rendimiento_ilegible_viaja_como_null():
    p = privacy.payload_chat(ITEM, [dict(COMP, rendimiento="abc")], CATALOGO)
    assert p["composicion_actual"][0]["rendimiento"] is None


def test_insumo_encontrado_copia_campo_por_campo_sin_precio():
    ins = Insumo("4279", "CUADRILLA", "HR", "SUELDOS Y JORNALES", 40000, "COSTO INTERNO")
    obs = RendimientoObservado("4279", "HR", 14, 0.4, 0.62, 1.1)
    d = privacy.insumo_encontrado_to_dict(ins, obs)
    privacy.assert_no_money(d)
    assert "40000" not in json.dumps(d)
    assert d["insumo_codigo"] == "4279" and d["grupo"] == "SUELDOS Y JORNALES"
    assert d["rendimientos_observados"]["mediana"] == 0.62
    assert privacy.insumo_encontrado_to_dict(ins, None)["rendimientos_observados"] is None
```

- [ ] **Step 2: Correr y ver que fallan**

Run: `python -m pytest tests/test_privacy_chat.py -q`
Expected: FAIL con `AttributeError: module 'apu_tool.dominio.privacy' has no attribute 'payload_chat'`

- [ ] **Step 3: Implementar**

En `apu_tool/dominio/privacy.py`, agregar después de `payload_composicion`:

```python
def _rendimiento_o_none(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return round(x, 6) if math.isfinite(x) else None


def componente_mesa_to_dict(c: dict, catalogo: dict) -> dict[str, Any]:
    """Un componente de la mesa tal como lo ve el agente del chat.

    Los componentes los manda el CLIENTE (la tabla tal como está en pantalla), así que
    se copian clave por clave y SOLO los campos estructurados. `justificacion` e
    `hipotesis` NO viajan: son texto libre que una persona pudo editar, y un monto
    adentro pasaría por `assert_no_money` sin que nada salte. Nombre y unidad salen del
    catálogo (`catalogo`, ya filtrado a nombre/unidad/grupo), no del cliente.
    """
    cod = str(c.get("codigo", "") or "")[:40]
    info = catalogo.get(cod) or {}
    return {"codigo": cod, "nombre": info.get("nombre", ""),
            "unidad": info.get("unidad", ""),
            "funcion": str(c.get("funcion", "") or "")[:40],
            "rendimiento": _rendimiento_o_none(c.get("rendimiento")),
            "origen": str(c.get("origen", "") or "")[:40]}


def payload_chat(item, componentes: list, catalogo: dict) -> dict[str, Any]:
    """El contexto que acompaña cada mensaje del chat de composición: la actividad
    (sin `precio_contractual`) y la composición que la persona ve en pantalla."""
    return {"actividad": licitacion_item_to_dict(item),
            "composicion_actual": [componente_mesa_to_dict(c, catalogo)
                                   for c in componentes if isinstance(c, dict)]}


def insumo_encontrado_to_dict(ins, observado=None) -> dict[str, Any]:
    """Un resultado de `buscar_insumos`. `ins` es un `Insumo`, que LLEVA `precio` y
    `fuente_precio`: por eso se copia campo por campo y nunca se vuelca."""
    return {"insumo_codigo": ins.codigo, "insumo_nombre": ins.nombre,
            "unidad": ins.unidad, "grupo": ins.grupo,
            "rendimientos_observados": (rendimiento_observado_to_dict(observado)
                                        if observado is not None else None)}
```

- [ ] **Step 4: Correr y ver que pasan**

Run: `python -m pytest tests/test_privacy_chat.py tests/test_privacy.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/privacy.py tests/test_privacy_chat.py
git commit -m "feat(privacy): payloads des-monetizados del chat de composicion

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: La llamada al SDK del chat (`ApuAdvisor.turno_chat`)

**Files:**
- Modify: `apu_tool/dominio/ai_assist.py`
- Test: `tests/test_composicion_chat_advisor.py` (crear)

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_composicion_chat_advisor.py`:

```python
"""La puerta al SDK del chat: una vuelta del bucle, sin llamar a la API real."""
import json
from types import SimpleNamespace

import pytest

from apu_tool.dominio import ai_assist
from apu_tool.dominio.ai_assist import (
    HERRAMIENTAS_CHAT, MSG_CREDENCIAL, MSG_SIN_SALDO, ApuAdvisor, IANoDisponible,
)


def advisor_con_cliente(create):
    a = ApuAdvisor(enabled=False)
    a.enabled = True
    a.model = "modelo-x"
    a._client = SimpleNamespace(messages=SimpleNamespace(create=create))
    return a


def test_pide_herramientas_salida_estructurada_y_esfuerzo_bajo():
    visto = {}
    a = advisor_con_cliente(lambda **kw: visto.update(kw) or "resp")
    assert a.turno_chat([{"role": "user", "content": "hola"}],
                        con_herramientas=True) == "resp"
    assert visto["model"] == "modelo-x"
    assert visto["tools"] == HERRAMIENTAS_CHAT
    assert visto["tool_choice"] == {"type": "auto"}
    assert visto["thinking"] == {"type": "adaptive"}
    assert visto["output_config"]["effort"] == "low"
    assert visto["output_config"]["format"]["type"] == "json_schema"


def test_en_el_tope_apaga_las_herramientas_sin_forzar_ninguna():
    """`tool_choice` forzado (any/tool) da 400 en los modelos nuevos: el tope se
    cierra con `none`, que todos aceptan, y las herramientas siguen declaradas
    porque el historial ya tiene bloques tool_use."""
    visto = {}
    a = advisor_con_cliente(lambda **kw: visto.update(kw))
    a.turno_chat([], con_herramientas=False)
    assert visto["tool_choice"] == {"type": "none"}
    assert visto["tools"] == HERRAMIENTAS_CHAT


def test_los_esquemas_no_usan_lo_que_la_salida_estructurada_rechaza():
    texto = json.dumps([ai_assist._ESQUEMA_CHAT, HERRAMIENTAS_CHAT])
    assert "minimum" not in texto and "maximum" not in texto


def test_el_esquema_del_componente_es_el_mismo_de_componer():
    """Mismo contrato, mismo acotado: sin `apu` en tipo ni `sub_apu` en funcion."""
    item = ai_assist._ESQUEMA_CHAT["properties"]["cambios"]["items"]
    comp = item["properties"]["componente"]
    assert comp["type"] == ["object", "null"]
    assert comp["properties"]["tipo"]["enum"] == ["insumo"]
    assert "sub_apu" not in comp["properties"]["funcion"]["enum"]


def test_sin_credencial_levanta_ia_no_disponible():
    a = ApuAdvisor(enabled=False)
    with pytest.raises(IANoDisponible, match="ANTHROPIC_API_KEY"):
        a.turno_chat([], con_herramientas=True)


class _ErrorApi(Exception):
    def __init__(self, status_code, message="x"):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def test_traduce_credencial_invalida():
    def create(**_kw):
        raise _ErrorApi(401)
    with pytest.raises(IANoDisponible) as e:
        advisor_con_cliente(create).turno_chat([], con_herramientas=True)
    assert str(e.value) == MSG_CREDENCIAL


def test_traduce_sin_saldo():
    def create(**_kw):
        raise _ErrorApi(400, "Your credit balance is too low")
    with pytest.raises(IANoDisponible) as e:
        advisor_con_cliente(create).turno_chat([], con_herramientas=True)
    assert str(e.value) == MSG_SIN_SALDO


def test_otros_errores_suben_tal_cual():
    def create(**_kw):
        raise _ErrorApi(529)
    with pytest.raises(_ErrorApi):
        advisor_con_cliente(create).turno_chat([], con_herramientas=True)


def test_revienta_antes_de_la_red_si_hay_una_clave_monetaria():
    llamado = []
    a = advisor_con_cliente(lambda **kw: llamado.append(kw))
    with pytest.raises(ai_assist.privacy.PrivacyViolation):
        a.turno_chat([{"role": "user", "content": [{"precio": 1}]}],
                     con_herramientas=True)
    assert llamado == []
```

- [ ] **Step 2: Correr y ver que fallan**

Run: `python -m pytest tests/test_composicion_chat_advisor.py -q`
Expected: FAIL con `ImportError: cannot import name 'HERRAMIENTAS_CHAT'`

- [ ] **Step 3: Implementar las constantes**

En `apu_tool/dominio/ai_assist.py`, después de `_ESQUEMA_COMPOSICION` y antes de `class ApuAdvisor`:

```python
# --------------------------------------------------------------------- chat
# El chat de la mesa de composición (`dominio/composicion_chat.py`). Misma puerta al
# SDK que `componer`, misma traducción de errores; distinto contrato: una vuelta de
# un bucle de tool use, que termina en `{texto, cambios}`.
PROMPT_VERSION_CHAT = "chat/v1"   # se sube A MANO al tocar el prompt o los esquemas

_SISTEMA_CHAT = """\
Eres un ingeniero de costos de obra civil que ayuda a una persona a completar la
composición de un APU (análisis de precios unitarios) en una mesa de revisión. Con
cada mensaje recibes la ACTIVIDAD y la COMPOSICIÓN ACTUAL de la mesa (lo que la
persona ve en pantalla) y su instrucción.

Herramientas:
- `buscar_insumos(texto)`: busca en el catálogo por palabras del nombre. Devuelve
  código, nombre, unidad, grupo y con qué rendimientos aparece el insumo en la
  biblioteca.
- `buscar_apus(texto)`: busca APUs de la biblioteca parecidos, con su composición.
Busca con palabras cortas del nombre ("oficial", "soldador", "retroexcavadora"), no
con frases. Si una búsqueda no trae nada útil, reformúlala con otras palabras. Tienes
un máximo de 4 búsquedas por mensaje.

Reglas estrictas:
- Solo PROPONES cambios; la persona decide si los aplica. No digas que ya los
  aplicaste.
- Usa ÚNICAMENTE códigos que viste en un resultado de búsqueda o que ya están en la
  composición actual. No inventes códigos.
- NUNCA recibirás precios ni costos, y no debes inventarlos ni pedirlos.
- Los rendimientos son cantidades FÍSICAS por unidad de la actividad.
- `op`: "agregar" un insumo que no está; "modificar" uno que ya está (manda el
  componente completo con el cambio); "quitar" uno que está (`componente` en null).
- En `componente`, `origen` dice de dónde sale el rendimiento. Sé honesto:
  "copiado_de_antecedente" o "ajustado_de_antecedente" solo si sale de un APU que
  viste en `buscar_apus` (cítalo en `referencias`); "calculado_desde_produccion" si
  hiciste una cuenta (escríbela en `calculo`); "supuesto_tecnico" si es criterio;
  "sin_evidencia" si no tienes en qué apoyarte.
- `hipotesis` va como lista de pares clave-valor (el valor como texto), o [].
- Si la persona pregunta algo y no pide cambios, responde en `texto` y deja
  `cambios` vacío.
- `texto` es lo que lee la persona: corto, en español de Colombia y tuteando.

Responde EXCLUSIVAMENTE con un JSON válido con el esquema pedido.
"""

# El componente es EL MISMO de `componer`, acotado igual (tipo solo `insumo`, sin
# `sub_apu`): lo parsea el mismo `propuesta_desde_json`. Nullable porque `quitar` no
# lleva componente.
_COMPONENTE_ESQUEMA = _ESQUEMA_COMPOSICION["properties"]["componentes"]["items"]
OPS_CHAT = ("agregar", "modificar", "quitar")

_ESQUEMA_CHAT = {
    "type": "object",
    "properties": {
        "texto": {"type": "string"},
        "cambios": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": list(OPS_CHAT)},
                    "codigo": {"type": "string"},
                    "componente": {**_COMPONENTE_ESQUEMA,
                                   "type": ["object", "null"]},
                },
                "required": ["op", "codigo", "componente"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["texto", "cambios"],
    "additionalProperties": False,
}


def _herramienta(nombre: str, descripcion: str, campo: str) -> dict:
    return {"name": nombre, "description": descripcion, "strict": True,
            "input_schema": {"type": "object",
                             "properties": {"texto": {"type": "string",
                                                      "description": campo}},
                             "required": ["texto"], "additionalProperties": False}}


HERRAMIENTAS_CHAT = [
    _herramienta("buscar_insumos",
                 "Busca insumos del catálogo por palabras de su nombre. Devuelve hasta "
                 "15 con código, nombre, unidad, grupo y los rendimientos con que "
                 "aparecen en la biblioteca. No devuelve precios.",
                 "Palabras cortas del nombre del insumo, p. ej. 'oficial soldador'."),
    _herramienta("buscar_apus",
                 "Busca APUs de la biblioteca parecidos a un texto. Devuelve hasta 5 "
                 "con su composición (insumos, unidades y rendimientos). No devuelve "
                 "precios.",
                 "Descripción corta de la actividad, p. ej. 'excavación manual'."),
]
MAX_TOKENS_CHAT = 16000
```

- [ ] **Step 4: Implementar los métodos**

Dentro de `class ApuAdvisor`, al final (después de `_pedir_al_sdk`):

```python
    def turno_chat(self, mensajes: list, *, con_herramientas: bool):
        """UNA vuelta del bucle del chat. Devuelve la respuesta cruda del SDK.

        El bucle (ejecutar herramientas, cortar en el tope) vive en
        `dominio/composicion_chat.py`; acá solo se habla con el modelo y se traducen
        los errores de configuración, igual que en `componer`.

        `con_herramientas=False` apaga las herramientas con `tool_choice: none` SIN
        sacarlas de `tools`: el historial ya trae bloques `tool_use` que las nombran.
        No se usa `tool_choice` forzado: los modelos nuevos lo rechazan con 400.
        """
        if not self.enabled or self._client is None:
            if getattr(self, "_sdk_ausente", False):
                raise IANoDisponible(
                    "Conversar con el agente necesita el SDK de anthropic instalado "
                    "en el servidor.")
            raise IANoDisponible(
                "Conversar con el agente necesita ANTHROPIC_API_KEY en el servidor.")
        # FUERA del try, como en `componer`: el invariante #1 nunca se traga. Los
        # bloques del SDK (no-dict) no se recorren; lo que armamos nosotros, sí.
        privacy.assert_no_money(mensajes)
        try:
            return self._pedir_chat_al_sdk(mensajes, con_herramientas)
        except Exception as exc:
            if credencial_invalida(exc):
                raise IANoDisponible(MSG_CREDENCIAL) from exc
            if sin_saldo(exc):
                raise IANoDisponible(MSG_SIN_SALDO) from exc
            raise

    def _pedir_chat_al_sdk(self, mensajes: list, con_herramientas: bool):
        """La llamada pelada. Aparte para que los tests la sustituyan sin simular el
        cliente, igual que `_pedir_al_sdk`."""
        return self._client.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS_CHAT,
            system=_SISTEMA_CHAT,
            thinking={"type": "adaptive"},
            # `low`: una instrucción puntual no necesita el razonamiento de una
            # composición entera, y el pensamiento es la parte que domina el costo.
            output_config={"effort": "low",
                           "format": {"type": "json_schema", "schema": _ESQUEMA_CHAT}},
            tools=HERRAMIENTAS_CHAT,
            tool_choice={"type": "auto"} if con_herramientas else {"type": "none"},
            messages=mensajes,
        )
```

- [ ] **Step 5: Correr y ver que pasan**

Run: `python -m pytest tests/test_composicion_chat_advisor.py tests/test_composicion_advisor.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apu_tool/dominio/ai_assist.py tests/test_composicion_chat_advisor.py
git commit -m "feat(ia): turno del chat de composicion (tools + salida estructurada)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Las herramientas del agente (`composicion_chat.Herramientas`)

**Files:**
- Create: `apu_tool/dominio/composicion_chat.py`
- Create: `tests/chat_falso.py`
- Test: `tests/test_composicion_chat_motor.py` (crear)

- [ ] **Step 1: Crear el doble de pruebas compartido**

Crear `tests/chat_falso.py` (lo usan esta tarea, la 6 y la 8):

```python
"""Respuestas falsas del SDK para el chat de composición. No se llama a la API real:
se sustituye `_pedir_chat_al_sdk`, la única puerta, como en los tests de `componer`."""
import json
from types import SimpleNamespace

from apu_tool.dominio.ai_assist import ApuAdvisor

USO = SimpleNamespace(input_tokens=10, output_tokens=5)


def resp_herramienta(*llamadas, prefijo="t"):
    """Una respuesta que pide herramientas: llamadas = (nombre, texto), ..."""
    bloques = [SimpleNamespace(type="tool_use", id=f"{prefijo}{i}", name=n,
                               input={"texto": t})
               for i, (n, t) in enumerate(llamadas)]
    return SimpleNamespace(stop_reason="tool_use", content=bloques, usage=USO)


def resp_final(texto="Listo.", cambios=(), stop_reason="end_turn", crudo=None):
    cuerpo = crudo if crudo is not None else json.dumps(
        {"texto": texto, "cambios": list(cambios)})
    return SimpleNamespace(stop_reason=stop_reason,
                           content=[SimpleNamespace(type="text", text=cuerpo)],
                           usage=USO)


def componente(codigo="6092", rendimiento=1.0, funcion="herramienta"):
    return {"codigo": codigo, "tipo": "insumo", "funcion": funcion,
            "rendimiento": rendimiento, "origen": "supuesto_tecnico",
            "referencias": [], "hipotesis": [], "calculo": None,
            "justificacion": "j", "nivel_evidencia": "bajo"}


class AdvisorGuion(ApuAdvisor):
    """Devuelve las respuestas del guion en orden y anota cada llamada."""

    def __init__(self, respuestas):
        self.enabled = True
        self._client = object()
        self.model = "falso"
        self.respuestas = list(respuestas)
        self.llamadas = []

    def _pedir_chat_al_sdk(self, mensajes, con_herramientas):
        self.llamadas.append({"mensajes": list(mensajes),
                              "con_herramientas": con_herramientas})
        return self.respuestas.pop(0)
```

- [ ] **Step 2: Escribir los tests que fallan**

Crear `tests/test_composicion_chat_motor.py`:

```python
"""El chat de composición: herramientas y bucle. El SDK se sustituye."""
import json

import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.composicion_chat import Herramientas
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem

ITEM = LicitacionItem("1.3", "EXCAVACION MANUAL EN MATERIAL COMUN", "M3", 120.0,
                      180000.0, "DIURNO")


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "precios.db", tmp_path / "apus.db",
                tmp_path / "corridas.db")
    a.reset()
    a.precios.insert_insumos([
        Insumo("4279", "CUADRILLA OFICIAL MAS AYUDANTES", "HR", "SUELDOS Y JORNALES",
               40000, "PRECIO IDU"),
        Insumo("6092", "HERRAMIENTA MENOR", "GLB", "EQ", 2000, "PRECIO IDU"),
        Insumo("7001", "OFICIAL SOLDADOR CERTIFICADO", "HR", "SUELDOS Y JORNALES",
               55000, "COSTO INTERNO"),
        Insumo("7002", "SOLDADOR VIEJO", "HR", "SUELDOS Y JORNALES", 50000,
               "COSTO INTERNO"),
    ])
    oculto = a.precios.search_insumos("SOLDADOR VIEJO")[0]
    a.precios.set_oculto(oculto.id, True)
    a.apus.insert_apus([
        Apu("A1", "EXCAVACION MANUAL COMUN", "M3", "DIURNO", "EXCAVACIONES")])
    a.apus.insert_components([
        ApuComponent("A1", "DIURNO", "4279", "CUADRILLA", "HR", 0.62, 40000),
        ApuComponent("A1", "DIURNO", "6092", "HERRAMIENTA MENOR", "GLB", 1.0, 2000),
    ])
    return a


# --- herramientas ------------------------------------------------------------
def test_buscar_insumos_trae_visibles_sin_precio(alm):
    r = Herramientas(alm, "DIURNO").ejecutar("buscar_insumos", {"texto": "soldador"})
    codigos = [i["insumo_codigo"] for i in r["insumos"]]
    assert codigos == ["7001"]                       # 7002 está oculto
    texto = json.dumps(r)
    assert "55000" not in texto and "COSTO INTERNO" not in texto


def test_buscar_insumos_ordena_por_parecido_y_trae_lo_observado(alm):
    r = Herramientas(alm, "DIURNO").ejecutar("buscar_insumos",
                                             {"texto": "cuadrilla oficial"})
    assert r["insumos"][0]["insumo_codigo"] == "4279"
    assert r["insumos"][0]["rendimientos_observados"]["mediana"] == 0.62


def test_buscar_apus_trae_la_composicion_sin_precio(alm):
    r = Herramientas(alm, "DIURNO").ejecutar("buscar_apus",
                                             {"texto": "excavacion manual"})
    assert r["apus"][0]["codigo"] == "A1"
    assert {c["insumo_codigo"] for c in r["apus"][0]["componentes"]} == {"4279", "6092"}
    assert "40000" not in json.dumps(r)


def test_herramienta_desconocida_devuelve_error_y_no_revienta(alm):
    r = Herramientas(alm, "DIURNO").ejecutar("borrar_todo", {"texto": "x"})
    assert "error" in r


def test_una_busqueda_sin_palabras_utiles_devuelve_vacio(alm):
    r = Herramientas(alm, "DIURNO").ejecutar("buscar_insumos", {"texto": "de la"})
    assert r["insumos"] == []
```

- [ ] **Step 3: Correr y ver que fallan**

Run: `python -m pytest tests/test_composicion_chat_motor.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'apu_tool.dominio.composicion_chat'`

- [ ] **Step 4: Implementar**

Crear `apu_tool/dominio/composicion_chat.py`:

```python
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
from apu_tool.dominio import privacy
from apu_tool.dominio.ai_assist import OPS_CHAT, PROMPT_VERSION_CHAT, IANoDisponible
from apu_tool.dominio.compose import rendimientos_observados
from apu_tool.dominio.composicion import propuesta_desde_json
from apu_tool.dominio.matching import Matcher
from apu_tool.nucleo.relevancia import _tokens, similarity

logger = logging.getLogger(__name__)

MAX_RESULTADOS_INSUMOS = 15
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
        palabras = [t for t in _tokens(texto) if len(t) >= 3]
        if not palabras:
            return {"consulta": texto, "insumos": []}
        # ponytail: `search_insumos_por_palabras` es N+1 (hasta 61 round-trips en
        # Postgres; docs/pendientes-agente-composicion.md §6). Con 4 búsquedas por
        # mensaje es ~1-2 s contra Supabase, chico al lado de la llamada al modelo.
        # Arreglarlo allá arregla esto. Ya filtra `oculto = 0`.
        encontrados = self.alm.precios.search_insumos_por_palabras(palabras, limit=60)
        ordenados = sorted(encontrados, key=lambda i: similarity(texto, i.nombre),
                           reverse=True)[:MAX_RESULTADOS_INSUMOS]
        obs = rendimientos_observados(self.alm, [i.codigo for i in ordenados])
        return {"consulta": texto,
                "insumos": [privacy.insumo_encontrado_to_dict(i, obs.get(i.codigo))
                            for i in ordenados]}

    def buscar_apus(self, texto: str) -> dict:
        if self._matcher is None:
            self._matcher = Matcher(self.alm.apus.apu_index())
        apus = []
        for c in self._matcher.candidates(texto, self.shift,
                                          top_n=MAX_RESULTADOS_APUS):
            dp = self.alm.apus.get_depriced_apu(c.apu_codigo, self.shift)
            if dp is not None:
                apus.append(privacy.depriced_apu_to_dict(dp))
        return {"consulta": texto, "apus": apus}
```

(`json`, `replace`, `OPS_CHAT`, `PROMPT_VERSION_CHAT`, `IANoDisponible` y `propuesta_desde_json` los usa `conversar` en la Tarea 6; si un linter avisa antes, se deja.)

- [ ] **Step 5: Correr y ver que pasan**

Run: `python -m pytest tests/test_composicion_chat_motor.py -q`
Expected: PASS (5)

- [ ] **Step 6: Commit**

```bash
git add apu_tool/dominio/composicion_chat.py tests/chat_falso.py tests/test_composicion_chat_motor.py
git commit -m "feat(composicion): herramientas de busqueda del agente del chat

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: El bucle del chat (`composicion_chat.conversar`)

**Files:**
- Modify: `apu_tool/dominio/composicion_chat.py`
- Test: `tests/test_composicion_chat_motor.py`

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `tests/test_composicion_chat_motor.py`:

```python
from apu_tool.dominio import privacy
from apu_tool.dominio.composicion_chat import MAX_HERRAMIENTAS, conversar
from tests.chat_falso import (
    AdvisorGuion, componente, resp_final, resp_herramienta,
)

TABLA = [{"codigo": "4279", "tipo": "insumo", "funcion": "mano_de_obra",
          "rendimiento": 0.62, "origen": "copiado_de_antecedente"}]


def charla(*textos):
    """Historial alternado usuario/agente (el primero es del usuario)."""
    roles = ["usuario", "agente"]
    return [{"rol": roles[i % 2], "texto": t} for i, t in enumerate(textos)]


def correr(alm, advisor, mensajes, tabla=TABLA):
    return list(conversar(alm, ITEM, tabla, mensajes, advisor))


# --- candados antes de la IA --------------------------------------------------
@pytest.mark.parametrize("mensajes", [
    charla("agrega el cemento, cuesta $45.000"),
    charla("nos lo cotizaron a 45000", "Entendido.", "agrega un oficial"),
    charla("agrega un oficial", "el precio es 12.500", "y un ayudante"),
])
def test_un_monto_en_cualquier_mensaje_bloquea_sin_llamar_a_la_ia(alm, mensajes):
    a = AdvisorGuion([])
    evs = correr(alm, a, mensajes)
    assert [e for e, _ in evs] == ["bloqueado"]
    assert "IA no puede ver precios" in evs[0][1]["motivo"]
    assert a.llamadas == []


def test_sin_mensaje_final_del_usuario_es_error_sin_llamar(alm):
    a = AdvisorGuion([])
    evs = correr(alm, a, charla("hola", "Hola, ¿qué agrego?"))
    assert evs[0][0] == "error" and a.llamadas == []


# --- el bucle -------------------------------------------------------------------
def test_busca_y_responde_con_los_eventos_en_orden(alm):
    a = AdvisorGuion([
        resp_herramienta(("buscar_insumos", "soldador")),
        resp_final("Te propongo el soldador.",
                   [{"op": "agregar", "codigo": "7001",
                     "componente": componente("7001", 0.1, "mano_de_obra")}]),
    ])
    evs = correr(alm, a, charla("busca un soldador certificado"))
    assert [e for e, _ in evs] == ["pensando", "buscando", "pensando", "respuesta"]
    assert evs[1][1] == {"herramienta": "buscar_insumos", "consulta": "soldador"}
    resp = evs[-1][1]
    assert resp["texto"] == "Te propongo el soldador."
    assert resp["cambios"][0]["codigo"] == "7001"
    assert resp["cambios"][0]["componente"]["rendimiento"] == 0.1
    assert resp["catalogo"]["7001"]["nombre"] == "OFICIAL SOLDADOR CERTIFICADO"
    assert resp["prompt_version"] == "chat/v1" and resp["modelo"] == "falso"
    # la segunda vuelta lleva el resultado de la herramienta, sin precios
    resultado = a.llamadas[1]["mensajes"][-1]["content"][0]
    assert resultado["type"] == "tool_result" and resultado["tool_use_id"] == "t0"
    assert "OFICIAL SOLDADOR" in resultado["content"]
    assert "55000" not in resultado["content"]


def test_el_contexto_lleva_la_tabla_y_no_el_contractual(alm):
    a = AdvisorGuion([resp_final()])
    correr(alm, a, charla("¿qué le falta?"))
    ultimo = a.llamadas[0]["mensajes"][-1]
    contexto, pregunta = ultimo["content"][0]["text"], ultimo["content"][1]["text"]
    assert "CUADRILLA OFICIAL MAS AYUDANTES" in contexto     # nombre del catálogo
    assert "180000" not in contexto
    assert pregunta == "¿qué le falta?"


def test_el_historial_viaja_como_turnos_y_se_acota(alm):
    textos = [f"mensaje {i}" for i in range(25)]          # 25: termina en usuario
    a = AdvisorGuion([resp_final()])
    correr(alm, a, charla(*textos))
    enviados = a.llamadas[0]["mensajes"]
    assert len(enviados) <= 20
    assert enviados[0]["role"] == "user"                   # nunca arranca en el agente


def test_respeta_el_tope_de_busquedas(alm):
    guion = [resp_herramienta(("buscar_insumos", f"q{i}"), prefijo=f"v{i}-")
             for i in range(MAX_HERRAMIENTAS + 1)]
    a = AdvisorGuion(guion + [resp_final()])
    evs = correr(alm, a, charla("busca de todo"))
    assert [c["con_herramientas"] for c in a.llamadas] == (
        [True] * MAX_HERRAMIENTAS + [False, False])
    # la búsqueda que se pasó del tope no se ejecuta: vuelve como error
    pasada = a.llamadas[-1]["mensajes"][-1]["content"][0]
    assert pasada.get("is_error") is True
    assert evs[-1][0] == "respuesta"


def test_descarta_codigos_inexistentes_y_ocultos(alm):
    a = AdvisorGuion([resp_final("Ahí van.", [
        {"op": "agregar", "codigo": "INVENTADO", "componente": componente("INVENTADO")},
        {"op": "agregar", "codigo": "7002", "componente": componente("7002")},
        {"op": "agregar", "codigo": "6092", "componente": componente("6092")},
    ])])
    resp = correr(alm, a, charla("agrega cosas"))[-1][1]
    assert [c["codigo"] for c in resp["cambios"]] == ["6092"]
    assert {d["codigo"] for d in resp["descartados"]} == {"INVENTADO", "7002"}


def test_quitar_no_lleva_componente_y_modificar_si(alm):
    a = AdvisorGuion([resp_final("Ok.", [
        {"op": "quitar", "codigo": "4279", "componente": None},
        {"op": "modificar", "codigo": "6092", "componente": componente("6092", 2.0)},
        {"op": "modificar", "codigo": "6092", "componente": None},
    ])])
    resp = correr(alm, a, charla("cambia"))[-1][1]
    assert resp["cambios"][0] == {"op": "quitar", "codigo": "4279", "componente": None}
    assert resp["cambios"][1]["componente"]["rendimiento"] == 2.0
    assert len(resp["cambios"]) == 2 and resp["descartados"][0]["codigo"] == "6092"


def test_una_respuesta_ilegible_es_error_para_reintentar(alm):
    evs = correr(alm, AdvisorGuion([resp_final(crudo="{no es json")]), charla("x"))
    assert evs[-1][0] == "error"


def test_una_negativa_del_modelo_es_error(alm):
    evs = correr(alm, AdvisorGuion([resp_final(stop_reason="refusal")]), charla("x"))
    assert evs[-1][0] == "error"


def test_sin_credencial_es_un_evento_error(alm):
    a = AdvisorGuion([])
    a.enabled = False
    evs = correr(alm, a, charla("x"))
    assert evs[-1] == ("error", {"detail":
                       "Conversar con el agente necesita ANTHROPIC_API_KEY en el servidor."})


def test_un_fallo_de_red_es_error_y_no_tumba_el_stream(alm):
    class Caido(AdvisorGuion):
        def _pedir_chat_al_sdk(self, mensajes, con_herramientas):
            raise TimeoutError("se cayó")
    evs = correr(alm, Caido([]), charla("x"))
    assert evs[-1][0] == "error"
    assert "vuelve a intentar" in evs[-1][1]["detail"]


def test_la_privacy_violation_sube(alm, monkeypatch):
    monkeypatch.setattr(privacy, "payload_chat", lambda *a, **k: {"precio": 1})
    with pytest.raises(privacy.PrivacyViolation):
        correr(alm, AdvisorGuion([resp_final()]), charla("x"))
```

- [ ] **Step 2: Correr y ver que fallan**

Run: `python -m pytest tests/test_composicion_chat_motor.py -q`
Expected: FAIL con `ImportError: cannot import name 'MAX_HERRAMIENTAS'`

- [ ] **Step 3: Implementar**

Agregar al final de `apu_tool/dominio/composicion_chat.py`:

```python
# ----------------------------------------------------------------------- bucle
MAX_HERRAMIENTAS = 4           # búsquedas por mensaje
MAX_MENSAJES = 20              # historial que viaja al modelo
MAX_TEXTO_MENSAJE = 1000
# Vueltas del bucle: las de herramientas, más la que ya no puede buscar, más una de
# holgura. Un modelo que sigue pidiendo herramientas con `tool_choice: none` no
# debería existir; si existe, esto corta en vez de girar para siempre.
_MAX_VUELTAS = MAX_HERRAMIENTAS + 2
MSG_REINTENTAR = "No pude responder, vuelve a intentar."


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


def _catalogo(almacen: Almacen, codigos) -> dict[str, dict]:
    """Nombre, unidad y grupo por código, en UNA consulta. Campo por campo: el
    `Insumo` que devuelve el repo trae `precio`."""
    cods = sorted({str(c) for c in codigos if c})
    if not cods:
        return {}
    out = {}
    for cod, cands in almacen.precios.get_candidatos_bulk(cods).items():
        if cands:
            out[cod] = {"nombre": cands[0].nombre, "unidad": cands[0].unidad,
                        "grupo": cands[0].grupo}
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


def _respuesta(almacen: Almacen, data, modelo: str) -> dict:
    """La respuesta final, con los cambios filtrados por la plataforma.

    Un `agregar` cuyo código no existe o está oculto se DESCARTA antes de mostrarse, y
    se dice cuál y por qué: nunca se pierde en silencio. `modificar` sin componente
    también se descarta. `quitar` y `modificar` no se cruzan con el catálogo: el
    código ya está en la tabla, y si no está, `aplicarCambios` (web) lo reporta como
    conflicto.
    """
    data = data if isinstance(data, dict) else {}
    crudos = [c for c in (data.get("cambios") or []) if isinstance(c, dict)]
    codigos = [str(c.get("codigo", "") or "").strip()[:40] for c in crudos]
    catalogo = _catalogo(almacen, codigos)
    hay_altas = any(c.get("op") == "agregar" for c in crudos)
    # Una consulta, solo si hay altas: `get_candidatos_bulk` no filtra ocultos.
    visibles = ({cod for _, cod, _ in almacen.precios.todos_no_ocultos()}
                if hay_altas else set())
    cambios, descartados = [], []
    for c, cod in zip(crudos, codigos):
        op = c.get("op")
        if op not in OPS_CHAT or not cod:
            descartados.append({"codigo": cod, "motivo": "Cambio ilegible."})
            continue
        if op == "agregar" and (cod not in catalogo or cod not in visibles):
            descartados.append({"codigo": cod,
                                "motivo": "No está en el catálogo (o está oculto)."})
            continue
        comp = None
        if op != "quitar":
            p = propuesta_desde_json({"componentes": [c.get("componente")]})
            if not p.componentes:
                descartados.append({"codigo": cod,
                                    "motivo": "El agente no mandó el componente."})
                continue
            comp = replace(p.componentes[0], codigo=cod).to_dict()
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
    # TODOS, también los "del agente": el historial lo manda el cliente.
    for m in mensajes:
        motivo = privacy.texto_con_dinero(m["texto"])
        if motivo:
            yield ("bloqueado", {"motivo": motivo})
            return

    catalogo = _catalogo(almacen, [c.get("codigo") for c in componentes
                                   if isinstance(c, dict)])
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
            yield ("respuesta", _respuesta(almacen, data, advisor.model))
            return
        yield ("error", {"detail": MSG_REINTENTAR})
    except privacy.PrivacyViolation:
        raise                                   # el invariante #1 nunca se traga
    except IANoDisponible as exc:
        yield ("error", {"detail": str(exc)})
    except Exception:
        logger.exception("Falló una vuelta del chat de composición")
        yield ("error", {"detail": MSG_REINTENTAR})
```

- [ ] **Step 4: Correr y ver que pasan**

Run: `python -m pytest tests/test_composicion_chat_motor.py -q`
Expected: PASS (todos)

Nota para `test_respeta_el_tope_de_busquedas`: el guion tiene `MAX_HERRAMIENTAS + 1` respuestas con herramienta y una final, o sea 6 llamadas; las 4 primeras con `con_herramientas=True`, la 5ª (usadas=4) y la 6ª (usadas=5) con `False`.

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/composicion_chat.py tests/test_composicion_chat_motor.py
git commit -m "feat(composicion): bucle del chat con tope de busquedas y candado de dinero

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: El `PUT` acepta la instrucción del chat y la mesa vacía

**Files:**
- Modify: `apu_tool/servicio/composicion.py` (`guardar_edicion`, `_lista_blanca`, nuevo `_rastro_chat`)
- Modify: `apu_tool/servicio/esquemas.py` (`ComposicionEditarIn`)
- Test: `tests/test_api_composicion_chat.py` (crear)

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_api_composicion_chat.py`:

```python
"""El chat de la mesa: el PUT con instrucción, la mesa vacía y el endpoint SSE."""
from apu_tool import config
from apu_tool.servicio import composicion as composicion_svc
from tests.chat_falso import AdvisorGuion, componente, resp_final
from tests.conftest import cliente
from tests.test_api_composicion import (  # noqa: F401  (fixtures reusadas)
    COMPONENTES, _sembrar, app_alm, corrida,
)

URL = "/api/corridas/{cid}/composicion/1"


# --- PUT con instrucción -------------------------------------------------------
def test_put_con_instruccion_deja_el_rastro_del_chat(app_alm, corrida):
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    r = cliente(app, "editor").put(URL.format(cid=corrida), json={
        "version_base": 1, "componentes": COMPONENTES,
        "instruccion": "agrega un oficial"})
    assert r.status_code == 200
    v = alm.composiciones.vigente(corrida, 1)
    assert (v.version, v.estado) == (2, "editada")
    assert v.motivo == "chat: agrega un oficial"
    assert v.prompt_version == "chat/v1"
    assert v.modelo == config.AI_MODEL


def test_put_sin_instruccion_se_comporta_como_siempre(app_alm, corrida):
    """Regresión: la edición a mano hereda modelo y prompt de la generación."""
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    r = cliente(app, "editor").put(URL.format(cid=corrida), json={
        "version_base": 1, "componentes": COMPONENTES})
    assert r.status_code == 200
    v = alm.composiciones.vigente(corrida, 1)
    assert v.motivo is None
    assert (v.modelo, v.prompt_version) == ("falso", "composicion/v4")


def test_put_con_dinero_en_la_instruccion_es_422_y_no_escribe(app_alm, corrida):
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    r = cliente(app, "editor").put(URL.format(cid=corrida), json={
        "version_base": 1, "componentes": COMPONENTES,
        "instruccion": "pon el cemento a $45.000"})
    assert r.status_code == 422
    assert "IA no puede ver precios" in r.json()["detail"]
    assert len(alm.composiciones.historial(corrida, 1)) == 1


# --- mesa vacía ------------------------------------------------------------------
def test_mesa_vacia_el_primer_put_crea_la_version_1(app_alm, corrida):
    app, alm = app_alm
    r = cliente(app, "editor").put(URL.format(cid=corrida), json={
        "version_base": 0, "componentes": COMPONENTES,
        "instruccion": "arma una cuadrilla"})
    assert r.status_code == 200
    v = alm.composiciones.vigente(corrida, 1)
    assert (v.version, v.estado) == (1, "editada")
    assert v.antecedentes == {"codigos_permitidos": ["4279"], "apus_referencia": []}
    assert v.actividad["descripcion"] == alm.corridas.get_item(corrida, 1).item.descripcion


def test_mesa_vacia_con_version_base_distinta_de_0_es_404(app_alm, corrida):
    app, _ = app_alm
    r = cliente(app, "editor").put(URL.format(cid=corrida), json={
        "version_base": 1, "componentes": COMPONENTES})
    assert r.status_code == 404


def test_mesa_vacia_sobre_un_expediente_de_otra_actividad_sigue_la_numeracion(
        app_alm, corrida):
    """El seq se reusa: la versión nueva va después de la del expediente ajeno."""
    app, alm = app_alm
    _sembrar(alm, corrida, version=1, descripcion="OTRA ACTIVIDAD")
    r = cliente(app, "editor").put(URL.format(cid=corrida), json={
        "version_base": 0, "componentes": COMPONENTES})
    assert r.status_code == 200
    assert alm.composiciones.vigente(corrida, 1).version == 2
```

- [ ] **Step 2: Correr y ver que fallan**

Run: `python -m pytest tests/test_api_composicion_chat.py -q`
Expected: FAIL (`motivo` None en el primero; 404 en mesa vacía; 200 en el de dinero)

- [ ] **Step 3: Implementar el esquema**

En `apu_tool/servicio/esquemas.py`, al final de la clase `ComposicionEditarIn`:

```python
    # La instrucción del chat que originó estos cambios (Aplicar en el panel del
    # agente). Deja rastro en el expediente; sin ella, el PUT es el de siempre.
    instruccion: Optional[str] = Field(default=None, max_length=4000)
```

- [ ] **Step 4: Implementar el servicio**

En `apu_tool/servicio/composicion.py`:

1. Cambiar `from apu_tool.dominio import composicion_agente, privacy` por:
```python
from apu_tool.dominio import composicion_agente, composicion_chat, privacy
```

2. Cambiar la firma y la primera línea de código de `_lista_blanca`:
```python
def _lista_blanca(vigente: Optional[ComposicionRow],
                  componentes: list[dict]) -> frozenset[str]:
```
```python
    previos = set(((vigente.antecedentes if vigente else None) or {})
                  .get("codigos_permitidos", []))
```
y agregar al final de su docstring: "Sin vigente —la mesa vacía que se arma desde el chat— la lista es solo lo que se agregó."

3. Agregar antes de `guardar_edicion`:

```python
def _rastro_chat(datos: dict) -> dict:
    """Los campos del expediente que deja un Aplicar del chat, o {} si no viene de
    ahí. `modelo` y `prompt_version` los pone el SERVIDOR: son etiquetas para el
    reporte de correcciones y el cliente no las dicta.

    La instrucción ya pasó por el detector de dinero (es el mismo mensaje que se le
    mandó al agente), pero se vuelve a pasar: el cliente puede mandar otra, y el
    expediente tiene que seguir siendo una fila que se pueda reinyectar.
    """
    instr = (datos.get("instruccion") or "").strip()
    if not instr:
        return {}
    motivo = privacy.texto_con_dinero(instr)
    if motivo:
        raise ValueError(motivo)
    return {"motivo": f"chat: {instr[:1000]}", "modelo": config.AI_MODEL,
            "prompt_version": composicion_chat.PROMPT_VERSION_CHAT}
```

4. En `guardar_edicion`, reemplazar TODO el cuerpo (desde `if _exigir_activa(alm, corrida_id) is None:` hasta `return vista(alm, corrida_id, seq)`) por:

```python
    if _exigir_activa(alm, corrida_id) is None:
        return None
    row, hist, vig = _expediente(alm, corrida_id, seq)
    if row is None:
        return None
    if vig is None:
        # Mesa vacía: la fila no tiene expediente (o el que hay es de otra actividad,
        # porque el seq se reusa). Solo se arranca desde `version_base = 0`, y la
        # versión sigue la numeración del historial CRUDO, igual que `generar_stream`:
        # el índice único no sabe de qué actividad hablaba la otra.
        if int(datos["version_base"]) != 0:
            return None
        version = (hist[-1].version + 1) if hist else 1
    else:
        _exigir_version(vig, datos["version_base"])
        version = vig.version + 1
    rastro = _rastro_chat(datos)        # antes de escribir nada: 422 sin efectos

    comps = [dict(c) for c in datos.get("componentes", []) or []]
    previa = (vig.propuesta if vig else None) or {}
    # Se reusa el parser del contrato (`propuesta_desde_json`) en vez de construir los
    # dataclasses a mano: la edición humana pasa por el MISMO acotado de textos y la
    # misma degradación conservadora de campos ilegibles que la respuesta del modelo.
    cruda = propuesta_desde_json({
        "componentes": comps,
        "supuestos": previa.get("supuestos", []),
        "incertidumbre_declarada": previa.get("incertidumbre_declarada", 0.0),
        "justificacion": previa.get("justificacion", ""),
    })
    ctx = composicion_agente.recuperar(
        alm, row.item,
        supuestos_confirmados=bool(datos.get("supuestos_confirmados")))
    blanca = _lista_blanca(vig, comps)
    propuesta, validacion, confianza = composicion_agente.evaluar(
        cruda, _con_lista_blanca(alm, ctx.validacion, blanca))

    fila = _sello(
        corrida_id, row, vig, version=version, estado="editada",
        autor=_email(actor), propuesta=propuesta.to_dict(),
        validacion=validacion.to_dict(), confianza=confianza.nivel,
        confianza_motivos=[m.to_dict() for m in confianza.motivos],
        # Las dos mitades de `antecedentes` con la MISMA política: la lista blanca
        # ampliada (no una re-derivada de un retrieve nuevo) y los APUs de referencia
        # de la generación. Es lo que la próxima edición va a leer como base.
        antecedentes={"codigos_permitidos": sorted(blanca),
                      "apus_referencia": ((vig.antecedentes if vig else None)
                                          or {}).get("apus_referencia", [])},
        **rastro)
    alm.composiciones.agregar(fila)
    return vista(alm, corrida_id, seq)
```

En su docstring, cambiar "Devuelve None si la corrida, la fila o el expediente de esta línea no existen." por "Devuelve None si la corrida o la fila no existen, o si no hay expediente de esta línea y `version_base` no es 0 (la mesa vacía arranca en 0). Lanza ValueError (422) si la `instruccion` del chat trae dinero."

- [ ] **Step 5: Correr los tests nuevos y los de siempre**

Run: `python -m pytest tests/test_api_composicion_chat.py tests/test_api_composicion.py tests/test_servicio_privacidad.py -q`
Expected: PASS

Si `test_servicio_privacidad` falla: `servicio/composicion.py` no puede nombrar la fachada del SDK en ningún texto, ni en comentarios.

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/composicion.py apu_tool/servicio/esquemas.py tests/test_api_composicion_chat.py
git commit -m "feat(composicion): el PUT de la mesa acepta la instruccion del chat y la mesa vacia

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: El endpoint del chat y `ia_disponible` en la vista

**Files:**
- Modify: `apu_tool/servicio/composicion.py` (`chat_stream`, `vista`)
- Modify: `apu_tool/servicio/esquemas.py` (`MensajeChatIn`, `ChatComposicionIn`)
- Modify: `apu_tool/servicio/rutas.py`
- Modify: `tests/test_api_composicion.py`
- Test: `tests/test_api_composicion_chat.py`

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `tests/test_api_composicion_chat.py`:

```python
# --- POST .../chat (SSE) -----------------------------------------------------
CHAT = "/api/corridas/{cid}/composicion/{seq}/chat"
CUERPO = {"mensajes": [{"rol": "usuario", "texto": "agrega herramienta menor"}],
          "componentes": COMPONENTES}


def _con_guion(monkeypatch, respuestas):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    a = AdvisorGuion(respuestas)
    monkeypatch.setattr(composicion_svc, "ApuAdvisor", lambda: a)
    return a


def test_chat_responde_por_sse_y_no_persiste_nada(app_alm, corrida, monkeypatch):
    app, alm = app_alm
    _con_guion(monkeypatch, [resp_final("Te propongo esto.", [
        {"op": "agregar", "codigo": "6092", "componente": componente("6092")}])])
    r = cliente(app, "editor").post(CHAT.format(cid=corrida, seq=1), json=CUERPO)
    assert r.status_code == 200
    assert "event: respuesta" in r.text and "6092" in r.text
    assert alm.composiciones.historial(corrida, 1) == []


def test_chat_con_dinero_responde_bloqueado_sin_llamar(app_alm, corrida, monkeypatch):
    app, _ = app_alm
    a = _con_guion(monkeypatch, [])
    cuerpo = dict(CUERPO, mensajes=[{"rol": "usuario", "texto": "cuesta $45.000"}])
    r = cliente(app, "editor").post(CHAT.format(cid=corrida, seq=1), json=cuerpo)
    assert "event: bloqueado" in r.text
    assert a.llamadas == []


def test_chat_con_rol_consulta_es_403(app_alm, corrida, monkeypatch):
    app, _ = app_alm
    _con_guion(monkeypatch, [])
    r = cliente(app, "consulta").post(CHAT.format(cid=corrida, seq=1), json=CUERPO)
    assert r.status_code == 403


def test_chat_sin_credencial_es_503(app_alm, corrida, monkeypatch):
    app, _ = app_alm
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = cliente(app, "editor").post(CHAT.format(cid=corrida, seq=1), json=CUERPO)
    assert r.status_code == 503


def test_chat_en_corrida_congelada_es_409(app_alm, corrida, monkeypatch):
    app, alm = app_alm
    _con_guion(monkeypatch, [])
    alm.corridas.set_modo(corrida, "congelada")
    r = cliente(app, "editor").post(CHAT.format(cid=corrida, seq=1), json=CUERPO)
    assert r.status_code == 409


def test_chat_de_una_fila_inexistente_es_404(app_alm, corrida, monkeypatch):
    app, _ = app_alm
    _con_guion(monkeypatch, [])
    r = cliente(app, "editor").post(CHAT.format(cid=corrida, seq=99), json=CUERPO)
    assert r.status_code == 404


def test_la_vista_dice_si_la_ia_esta_disponible(app_alm, corrida, monkeypatch):
    app, _ = app_alm
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    v = cliente(app, "consulta").get(URL.format(cid=corrida)).json()
    assert v["ia_disponible"] is True
```

Y en `tests/test_api_composicion.py`, reemplazar `test_get_sin_composicion_devuelve_vacio` por:

```python
def test_get_sin_composicion_devuelve_vacio(app_alm, corrida, monkeypatch):
    app, _ = app_alm
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = cliente(app, "consulta").get(f"/api/corridas/{corrida}/composicion/1")
    assert r.status_code == 200
    assert r.json() == {"vigente": None, "historial": [], "catalogo": {},
                        "corrida_modo": "activa", "costo_a_mano": False,
                        "ia_disponible": False}
```

- [ ] **Step 2: Correr y ver que fallan**

Run: `python -m pytest tests/test_api_composicion_chat.py tests/test_api_composicion.py -q`
Expected: FAIL (405/404 en el endpoint de chat; falta `ia_disponible`)

- [ ] **Step 3: Implementar esquemas**

En `apu_tool/servicio/esquemas.py`: cambiar `from typing import Optional` por `from typing import Literal, Optional` y, después de `ComposicionRechazarIn`:

```python
class MensajeChatIn(BaseModel):
    rol: Literal["usuario", "agente"]
    # Tope holgado: el servidor recorta a 1000 caracteres por mensaje antes de mandarlo
    # a la IA. Esto solo ataja cuerpos absurdos.
    texto: str = Field(max_length=4000)


class ChatComposicionIn(BaseModel):
    """El historial del chat (efímero: lo guarda el navegador) y la tabla tal como
    está en pantalla, sin guardar incluido. Nada de esto se persiste."""
    mensajes: list[MensajeChatIn] = Field(max_length=100)
    componentes: list[ComponenteComposicionIn] = Field(default_factory=list,
                                                       max_length=80)
```

- [ ] **Step 4: Implementar servicio**

En `apu_tool/servicio/composicion.py`:

1. En `vista`, en el dict del `return`, reemplazar la última entrada:
```python
            "costo_a_mano": (row.costo_manual or 0) > 0}
```
por:
```python
            "costo_a_mano": (row.costo_manual or 0) > 0,
            # Para que el panel del agente se apague ANTES del primer mensaje en vez
            # de contestar 503. Misma condición que el botón "Componer".
            "ia_disponible": config.ai_available()}
```

2. Después de `_eventos` (fin de la sección de generación), agregar:

```python
# ----------------------------------------------------------------------- chat
def chat_stream(alm: Almacen, corrida_id: int, seq: int, datos: dict, actor=None):
    """El generador de eventos del chat, o None si la corrida o la fila no existen.

    Igual que `generar_stream`: todo lo que puede fallar antes de empezar se valida
    acá, con el stream cerrado. Lanza CorridaCongelada (409) e IANoDisponible (503).
    NO persiste nada: el chat propone, y aplicar pasa por `guardar_edicion`.
    """
    if _exigir_activa(alm, corrida_id) is None:
        return None
    row = alm.corridas.get_item(corrida_id, seq)
    if row is None:
        return None
    if not config.ai_available():
        raise IANoDisponible(
            "Conversar con el agente necesita ANTHROPIC_API_KEY en el servidor.")
    return composicion_chat.conversar(
        alm, row.item, datos.get("componentes") or [], datos.get("mensajes") or [],
        ApuAdvisor())
```

- [ ] **Step 5: Implementar la ruta**

En `apu_tool/servicio/rutas.py`: agregar `ChatComposicionIn` al import desde `apu_tool.servicio.esquemas` (donde ya se importa `ComposicionEditarIn`). Después de `componer_composicion`, agregar:

```python
@router.post("/corridas/{cid}/composicion/{seq}/chat")
def chat_composicion(cid: int, seq: int, body: ChatComposicionIn,
                     alm: Almacen = Depends(get_almacen),
                     actor=Depends(requiere_rol("editor"))):
    """Conversa con el agente sobre la composición de esta fila. Propone cambios;
    no escribe nada (aplicar es el PUT de la mesa)."""
    try:
        gen = composicion_svc.chat_stream(alm, cid, seq, body.model_dump(), actor)
    except svc.CorridaCongelada:
        raise HTTPException(status_code=409,
                            detail="La corrida está congelada; actívala para componer.")
    except svc.IANoDisponible as e:
        raise HTTPException(status_code=503, detail=str(e))
    if gen is None:
        raise HTTPException(status_code=404, detail="Fila no encontrada.")
    return StreamingResponse(_event_stream(gen),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})
```

Y actualizar el comentario de la sección ("Cinco endpoints sobre la MISMA fila…") a: "Seis endpoints sobre la MISMA fila: leer el expediente, generar (SSE), conversar con el agente (SSE), guardar la edición humana, aprobar y rechazar. `consulta` lee; los que escriben o gastan IA piden `editor`, incluido aprobar: da de alta un APU en la biblioteca."

- [ ] **Step 6: Correr y ver que pasan**

Run: `python -m pytest tests/test_api_composicion_chat.py tests/test_api_composicion.py tests/test_servicio_privacidad.py -q`
Expected: PASS

- [ ] **Step 7: Suite completa del backend**

Run: `python -m pytest tests/ -q`
Expected: todo verde (los de Postgres se saltan sin base local; esta feature no toca `datos/`).

- [ ] **Step 8: Commit**

```bash
git add apu_tool/servicio/composicion.py apu_tool/servicio/esquemas.py apu_tool/servicio/rutas.py tests/test_api_composicion_chat.py tests/test_api_composicion.py
git commit -m "feat(composicion): endpoint SSE del chat con el agente

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Tipos y cliente HTTP del chat (web)

**Files:**
- Modify: `web/src/lib/tipos.ts`
- Modify: `web/src/api/composicion.ts`

- [ ] **Step 1: Tipos**

En `web/src/lib/tipos.ts`, dentro de `interface VistaComposicion`, agregar al final:

```ts
  /** ¿Hay ANTHROPIC_API_KEY en el servidor? Apaga el panel del agente antes del
   *  primer mensaje. Opcional: los expedientes de tests viejos no lo traen. */
  ia_disponible?: boolean;
```

Y después de `VistaComposicion`:

```ts
/** Un mensaje del chat con el agente. El historial vive en el navegador (el chat es
 *  efímero); el servidor lo revisa entero contra montos antes de mandarlo a la IA. */
export interface MensajeChat {
  rol: "usuario" | "agente";
  texto: string;
}

export type OpCambioAgente = "agregar" | "modificar" | "quitar";

/** Un cambio propuesto por el agente. `componente` es null solo en `quitar`. */
export interface CambioAgente {
  op: OpCambioAgente;
  codigo: string;
  componente: ComponentePropuesto | null;
}

/** El evento `respuesta` del chat. `descartados` son cambios que la plataforma no
 *  dejó pasar (código inexistente u oculto): se muestran, nunca se pierden callados. */
export interface RespuestaAgente {
  texto: string;
  cambios: CambioAgente[];
  descartados: { codigo: string; motivo: string }[];
  catalogo: Record<string, EntradaCatalogo>;
  modelo: string;
  prompt_version: string;
}
```

- [ ] **Step 2: Cliente**

En `web/src/api/composicion.ts`:

1. Cambiar el import de tipos:
```ts
import type { ComponentePropuesto, MensajeChat, VistaComposicion } from "@/lib/tipos";
```

2. Reemplazar `guardarComposicion` por:
```ts
/** Guarda la edición humana. `versionBase` es la versión sobre la que se trabajó:
 *  si alguien se adelantó, el servidor devuelve 409 en vez de pisarla. Sin
 *  expediente todavía (mesa vacía), `versionBase` es 0.
 *
 *  `instruccion` llega solo desde el panel del agente: es el mensaje que originó los
 *  cambios y queda como rastro en el expediente ("chat: …"). */
export function guardarComposicion(
  id: number,
  seq: number,
  versionBase: number,
  componentes: ComponentePropuesto[],
  supuestosConfirmados: boolean,
  instruccion?: string,
): Promise<VistaComposicion> {
  return apiPut<VistaComposicion>(`/corridas/${id}/composicion/${seq}`, {
    version_base: versionBase,
    componentes,
    supuestos_confirmados: supuestosConfirmados,
    ...(instruccion ? { instruccion } : {}),
  });
}
```

3. Agregar al final:
```ts
/** Conversa con el agente (SSE). Eventos: `pensando`, `buscando` {herramienta,
 *  consulta}, `respuesta` (RespuestaAgente), `bloqueado` {motivo}, `error` {detail}.
 *  No persiste nada: aplicar es `guardarComposicion` con la instrucción. */
export function chatComposicionStream(
  id: number,
  seq: number,
  cuerpo: { mensajes: MensajeChat[]; componentes: ComponentePropuesto[] },
  onEvent: (e: EventoComposicion) => void,
): Promise<void> {
  return consumirSse(
    `/corridas/${id}/composicion/${seq}/chat`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cuerpo),
    },
    onEvent,
  );
}
```

- [ ] **Step 3: Verificar que compila**

Run: `cd web && npx tsc -b`
Expected: sin errores.

- [ ] **Step 4: Commit**

```bash
git add web/src/lib/tipos.ts web/src/api/composicion.ts
git commit -m "feat(web): tipos y cliente del chat con el agente

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: `aplicarCambios` (función pura)

**Files:**
- Create: `web/src/lib/cambiosAgente.ts`
- Test: `web/src/lib/cambiosAgente.test.ts`

- [ ] **Step 1: Escribir los tests que fallan**

Crear `web/src/lib/cambiosAgente.test.ts`:

```ts
import { expect, test } from "vitest";
import { aplicarCambios } from "./cambiosAgente";
import type { ComponentePropuesto } from "./tipos";

function comp(codigo: string, rendimiento = 1): ComponentePropuesto {
  return {
    codigo, tipo: "insumo", funcion: "material", rendimiento,
    origen: "supuesto_tecnico", referencias: [], hipotesis: {}, calculo: null,
    justificacion: "", nivel_evidencia: "bajo", ref_shift: "",
  };
}

test("agrega al final, quita y modifica por código", () => {
  const r = aplicarCambios([comp("A"), comp("B")], [
    { op: "agregar", codigo: "C", componente: comp("C", 3) },
    { op: "quitar", codigo: "A", componente: null },
    { op: "modificar", codigo: "B", componente: comp("B", 9) },
  ]);
  expect(r.componentes.map((c) => [c.codigo, c.rendimiento])).toEqual([["B", 9], ["C", 3]]);
  expect(r.conflictos).toEqual([]);
});

test("no duplica lo que ya está y lo reporta", () => {
  const r = aplicarCambios([comp("A")], [
    { op: "agregar", codigo: "A", componente: comp("A", 5) },
  ]);
  expect(r.componentes).toEqual([comp("A")]);
  expect(r.conflictos[0]).toMatch(/A ya estaba/);
});

test("quitar o modificar algo que ya no está es conflicto, y el resto se aplica", () => {
  const r = aplicarCambios([comp("A")], [
    { op: "quitar", codigo: "X", componente: null },
    { op: "modificar", codigo: "Y", componente: comp("Y") },
    { op: "agregar", codigo: "B", componente: comp("B") },
  ]);
  expect(r.componentes.map((c) => c.codigo)).toEqual(["A", "B"]);
  expect(r.conflictos).toHaveLength(2);
});

test("el código del cambio manda sobre el del componente", () => {
  const r = aplicarCambios([], [
    { op: "agregar", codigo: "C", componente: comp("OTRO") },
  ]);
  expect(r.componentes[0].codigo).toBe("C");
});

test("no muta la lista de entrada", () => {
  const actuales = [comp("A")];
  aplicarCambios(actuales, [{ op: "quitar", codigo: "A", componente: null }]);
  expect(actuales).toHaveLength(1);
});
```

- [ ] **Step 2: Correr y ver que fallan**

Run: `cd web && npx vitest run src/lib/cambiosAgente.test.ts`
Expected: FAIL (no existe el módulo)

- [ ] **Step 3: Implementar**

Crear `web/src/lib/cambiosAgente.ts`:

```ts
import type { CambioAgente, ComponentePropuesto } from "./tipos";

export interface ResultadoCambios {
  componentes: ComponentePropuesto[];
  /** Lo que no se pudo aplicar porque la tabla cambió desde que el agente propuso.
   *  Se muestra: un cambio que no entró nunca se pierde callado. */
  conflictos: string[];
}

/** Aplica los cambios del agente sobre la tabla de la mesa. Pura: no muta la
 *  entrada. Lo que choca (agregar algo que ya está; quitar o modificar algo que ya no
 *  está) se salta y se reporta, y el resto se aplica. */
export function aplicarCambios(
  actuales: ComponentePropuesto[],
  cambios: CambioAgente[],
): ResultadoCambios {
  let out = [...actuales];
  const conflictos: string[] = [];
  for (const c of cambios) {
    const i = out.findIndex((x) => x.codigo === c.codigo);
    if (c.op === "agregar") {
      if (i >= 0) {
        conflictos.push(`${c.codigo} ya estaba en la tabla: no se agregó otra vez.`);
      } else if (c.componente) {
        out = [...out, { ...c.componente, codigo: c.codigo }];
      }
    } else if (c.op === "quitar") {
      if (i < 0) {
        conflictos.push(`${c.codigo} ya no estaba en la tabla: no había nada que quitar.`);
      } else {
        out = out.filter((_, j) => j !== i);
      }
    } else {
      const nuevo = c.componente;
      if (i < 0) {
        conflictos.push(`${c.codigo} ya no estaba en la tabla: no se modificó.`);
      } else if (nuevo) {
        out = out.map((x, j) => (j === i ? { ...nuevo, codigo: c.codigo } : x));
      }
    }
  }
  return { componentes: out, conflictos };
}
```

- [ ] **Step 4: Correr y ver que pasan**

Run: `cd web && npx vitest run src/lib/cambiosAgente.test.ts`
Expected: PASS (5)

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/cambiosAgente.ts web/src/lib/cambiosAgente.test.ts
git commit -m "feat(web): aplicarCambios del agente sobre la tabla de la mesa

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: El avatar (`AvatarIngeniero`)

**Files:**
- Create: `web/src/components/composicion/AvatarIngeniero.tsx`
- Create: `web/src/components/composicion/AvatarIngeniero.css`
- Test: `web/src/components/composicion/AvatarIngeniero.test.tsx`

- [ ] **Step 1: Escribir el test que falla**

Crear `web/src/components/composicion/AvatarIngeniero.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import AvatarIngeniero, { type EstadoAvatar } from "./AvatarIngeniero";

const ESTADOS: EstadoAvatar[] = [
  "espera", "pensando", "buscando", "lista", "error", "deshabilitado",
];

test.each(ESTADOS)("el estado %s se expone en data-estado y en el aria-label", (e) => {
  render(<AvatarIngeniero estado={e} />);
  const img = screen.getByRole("img");
  expect(img.getAttribute("data-estado")).toBe(e);
  expect(img.getAttribute("aria-label")).toMatch(/agente/i);
});

test("cada estado tiene un aria-label distinto", () => {
  const etiquetas = new Set(ESTADOS.map((e) => {
    const { unmount } = render(<AvatarIngeniero estado={e} />);
    const l = screen.getByRole("img").getAttribute("aria-label");
    unmount();
    return l;
  }));
  expect(etiquetas.size).toBe(ESTADOS.length);
});
```

- [ ] **Step 2: Correr y ver que falla**

Run: `cd web && npx vitest run src/components/composicion/AvatarIngeniero.test.tsx`
Expected: FAIL (no existe el módulo)

- [ ] **Step 3: Implementar el componente**

Crear `web/src/components/composicion/AvatarIngeniero.tsx`:

```tsx
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
        <path className="av-manga" d="M46 64 L43 52 Q41 45 36 42" />
        <circle className="av-piel" cx="35" cy="41.5" r="3.2" />
      </g>
      {/* lista: pulgar arriba */}
      <g className="av-pulgar">
        <rect className="av-piel" x="47" y="41" width="7.5" height="8" rx="2" />
        <rect className="av-piel" x="49.2" y="35" width="3.2" height="7.5" rx="1.6" />
      </g>
      {/* buscando: lupa */}
      <g className="av-lupa">
        <circle cx="50" cy="40" r="5.5" />
        <line x1="54" y1="44" x2="59" y2="49" />
      </g>
    </svg>
  );
}
```

- [ ] **Step 4: Implementar el CSS**

Crear `web/src/components/composicion/AvatarIngeniero.css`:

```css
/* Avatar del agente de composición. Un estado por `data-estado`; cada uno con su
   gesto. Colores propios del dibujo (casco amarillo, chaleco naranja): se leen igual
   en tema claro y oscuro. */
.avatar-ing {
  --av-piel: #e0a878;
  --av-casco: #f2b705;
  --av-chaleco: #f97316;
  --av-trazo: #374151;
  flex-shrink: 0;
  overflow: visible;
}
.avatar-ing * { transform-box: fill-box; transform-origin: center; }
.avatar-ing .av-piel { fill: var(--av-piel); }
.avatar-ing .av-casco { fill: var(--av-casco); }
.avatar-ing .av-casco-cresta { fill: var(--av-casco); filter: brightness(0.9); }
.avatar-ing .av-chaleco { fill: var(--av-chaleco); }
.avatar-ing .av-franja { fill: #e5e7eb; }
.avatar-ing .av-ojos circle { fill: #1f2937; }
.avatar-ing .av-boca { fill: none; stroke: #7c4a2d; stroke-width: 1.4; stroke-linecap: round; }
.avatar-ing .av-manga { fill: none; stroke: var(--av-chaleco); stroke-width: 6; stroke-linecap: round; }
.avatar-ing .av-lupa circle { fill: rgba(255, 255, 255, 0.35); stroke: var(--av-trazo); stroke-width: 2.4; }
.avatar-ing .av-lupa line { stroke: var(--av-trazo); stroke-width: 3; stroke-linecap: round; }

/* Las partes de cada gesto solo existen en su estado. */
.avatar-ing .av-mano-barbilla,
.avatar-ing .av-pulgar,
.avatar-ing .av-lupa { display: none; }
.avatar-ing[data-estado="pensando"] .av-mano-barbilla { display: inline; }
.avatar-ing[data-estado="lista"] .av-pulgar { display: inline; }
.avatar-ing[data-estado="buscando"] .av-lupa { display: inline; }

/* espera: respira y parpadea */
.avatar-ing[data-estado="espera"] .av-cuerpo,
.avatar-ing[data-estado="espera"] .av-cabeza { animation: av-respira 3.2s ease-in-out infinite; }
.avatar-ing .av-ojos { animation: av-parpadea 4s infinite; }

/* pensando: ojos arriba y un balanceo lento */
.avatar-ing[data-estado="pensando"] .av-ojos { transform: translateY(-1.6px); animation: none; }
.avatar-ing[data-estado="pensando"] .av-cabeza { animation: av-ladea 2.4s ease-in-out infinite; }

/* buscando: la lupa barre y los ojos la siguen */
.avatar-ing[data-estado="buscando"] .av-lupa { animation: av-barre 1.4s ease-in-out infinite; }
.avatar-ing[data-estado="buscando"] .av-ojos { animation: av-mira 1.4s ease-in-out infinite; }

/* lista: pulgar arriba, una vez */
.avatar-ing[data-estado="lista"] .av-pulgar { animation: av-pulgar 0.9s ease-out 1 both; }

/* error: niega con la cabeza dos veces; casco en alerta */
.avatar-ing[data-estado="error"] { --av-casco: #dc2626; }
.avatar-ing[data-estado="error"] .av-cabeza { animation: av-niega 0.7s ease-in-out 2; }

/* deshabilitado: quieto y en gris */
.avatar-ing[data-estado="deshabilitado"] { filter: grayscale(1); opacity: 0.55; }
.avatar-ing[data-estado="deshabilitado"] * { animation: none !important; }

@keyframes av-respira { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.02); } }
@keyframes av-parpadea { 0%, 94%, 100% { transform: scaleY(1); } 97% { transform: scaleY(0.1); } }
@keyframes av-ladea { 0%, 100% { transform: rotate(0deg); } 50% { transform: rotate(-4deg); } }
@keyframes av-barre { 0%, 100% { transform: translateX(-7px) rotate(-8deg); } 50% { transform: translateX(3px) rotate(8deg); } }
@keyframes av-mira { 0%, 100% { transform: translateX(-1px); } 50% { transform: translateX(1.5px); } }
@keyframes av-pulgar {
  0% { transform: translateY(10px); opacity: 0; }
  40% { transform: translateY(-2px); opacity: 1; }
  70% { transform: translateY(1px); }
  100% { transform: translateY(0); }
}
@keyframes av-niega {
  0%, 100% { transform: rotate(0deg); }
  25% { transform: rotate(-9deg); }
  75% { transform: rotate(9deg); }
}

@media (prefers-reduced-motion: reduce) {
  .avatar-ing * { animation: none !important; }
}
```

- [ ] **Step 5: Correr y ver que pasa**

Run: `cd web && npx vitest run src/components/composicion/AvatarIngeniero.test.tsx`
Expected: PASS (7)

- [ ] **Step 6: Commit**

```bash
git add web/src/components/composicion/AvatarIngeniero.tsx web/src/components/composicion/AvatarIngeniero.css web/src/components/composicion/AvatarIngeniero.test.tsx
git commit -m "feat(web): avatar animado del agente (ingeniero con casco)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: El panel del chat (`PanelAgente`)

**Files:**
- Create: `web/src/components/composicion/PanelAgente.tsx`
- Test: `web/src/components/composicion/PanelAgente.test.tsx`

- [ ] **Step 1: Escribir los tests que fallan**

Crear `web/src/components/composicion/PanelAgente.test.tsx`:

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import PanelAgente from "./PanelAgente";
import type { ComponentePropuesto, RespuestaAgente } from "@/lib/tipos";

const chatComposicionStream = vi.fn();
vi.mock("@/api/composicion", () => ({
  chatComposicionStream: (...a: unknown[]) => chatComposicionStream(...a),
}));

const COMP: ComponentePropuesto = {
  codigo: "4279", tipo: "insumo", funcion: "mano_de_obra", rendimiento: 0.62,
  origen: "copiado_de_antecedente", referencias: [], hipotesis: {}, calculo: null,
  justificacion: "", nivel_evidencia: "alto", ref_shift: "",
};

const RESPUESTA: RespuestaAgente = {
  texto: "Te propongo el soldador.",
  cambios: [{ op: "agregar", codigo: "7001",
              componente: { ...COMP, codigo: "7001", rendimiento: 0.1,
                            referencias: [{ apu_codigo: "A1", turno: "DIURNO" }] } }],
  descartados: [{ codigo: "INVENTADO", motivo: "No está en el catálogo (o está oculto)." }],
  catalogo: { "7001": { nombre: "OFICIAL SOLDADOR", unidad: "HR", grupo: "MO" } },
  modelo: "m", prompt_version: "chat/v1",
};

type OnEv = (e: { event: string; data: unknown }) => void;

function montar(props: Partial<Parameters<typeof PanelAgente>[0]> = {}) {
  const onAplicar = vi.fn(async () => [] as string[]);
  render(
    <PanelAgente corridaId={1} seq={3} componentes={[COMP]} deshabilitado={null}
                 onAplicar={onAplicar} {...props} />,
  );
  return { onAplicar };
}

function escribirYEnviar(texto: string) {
  fireEvent.change(screen.getByRole("textbox"), { target: { value: texto } });
  fireEvent.click(screen.getByRole("button", { name: /enviar/i }));
}

beforeEach(() => {
  chatComposicionStream.mockReset();
});

test("manda el historial y la tabla, muestra la búsqueda y luego la propuesta", async () => {
  let soltar!: () => void;
  chatComposicionStream.mockImplementation(
    async (_id: number, _seq: number, _cuerpo: unknown, onEvent: OnEv) => {
      onEvent({ event: "buscando", data: { herramienta: "buscar_insumos", consulta: "soldador" } });
      await new Promise<void>((r) => { soltar = r; });
      onEvent({ event: "respuesta", data: RESPUESTA });
    });
  const { onAplicar } = montar();
  escribirYEnviar("busca un soldador");

  expect(await screen.findByText(/Buscando «soldador»/)).toBeTruthy();
  expect(screen.getByRole("img").getAttribute("data-estado")).toBe("buscando");
  expect(chatComposicionStream).toHaveBeenCalledWith(1, 3, {
    mensajes: [{ rol: "usuario", texto: "busca un soldador" }],
    componentes: [COMP],
  }, expect.any(Function));

  soltar();
  expect(await screen.findByText("Te propongo el soldador.")).toBeTruthy();
  expect(screen.getByText(/OFICIAL SOLDADOR/)).toBeTruthy();
  expect(screen.getByText(/INVENTADO/)).toBeTruthy();          // el descartado se ve

  fireEvent.click(screen.getByRole("button", { name: /^aplicar$/i }));
  await waitFor(() => expect(onAplicar).toHaveBeenCalledWith(
    RESPUESTA.cambios, "busca un soldador"));
  expect(await screen.findByText(/Aplicado/)).toBeTruthy();
});

test("un mensaje bloqueado vuelve a la caja y explica por qué", async () => {
  chatComposicionStream.mockImplementation(
    async (_i: number, _s: number, _c: unknown, onEvent: OnEv) => {
      onEvent({ event: "bloqueado", data: { motivo: "El mensaje parece traer un monto." } });
    });
  montar();
  escribirYEnviar("cuesta $45.000");
  expect(await screen.findByText(/parece traer un monto/)).toBeTruthy();
  expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("cuesta $45.000");
  expect(screen.getByRole("img").getAttribute("data-estado")).toBe("error");
});

test("descartar no llama a aplicar", async () => {
  chatComposicionStream.mockImplementation(
    async (_i: number, _s: number, _c: unknown, onEvent: OnEv) => {
      onEvent({ event: "respuesta", data: RESPUESTA });
    });
  const { onAplicar } = montar();
  escribirYEnviar("busca un soldador");
  fireEvent.click(await screen.findByRole("button", { name: /descartar/i }));
  expect(screen.getByText(/Descartado/)).toBeTruthy();
  expect(onAplicar).not.toHaveBeenCalled();
});

test("deshabilitado: muestra el motivo y no deja escribir", () => {
  montar({ deshabilitado: "El agente necesita ANTHROPIC_API_KEY en el servidor." });
  expect(screen.getByText(/ANTHROPIC_API_KEY/)).toBeTruthy();
  expect((screen.getByRole("textbox") as HTMLTextAreaElement).disabled).toBe(true);
  expect(screen.getByRole("img").getAttribute("data-estado")).toBe("deshabilitado");
});

test("los conflictos de aplicar se muestran", async () => {
  chatComposicionStream.mockImplementation(
    async (_i: number, _s: number, _c: unknown, onEvent: OnEv) => {
      onEvent({ event: "respuesta", data: RESPUESTA });
    });
  const onAplicar = vi.fn(async () => ["7001 ya estaba en la tabla: no se agregó otra vez."]);
  montar({ onAplicar });
  escribirYEnviar("x");
  fireEvent.click(await screen.findByRole("button", { name: /^aplicar$/i }));
  expect(await screen.findByText(/ya estaba en la tabla/)).toBeTruthy();
});
```

- [ ] **Step 2: Correr y ver que fallan**

Run: `cd web && npx vitest run src/components/composicion/PanelAgente.test.tsx`
Expected: FAIL (no existe el módulo)

- [ ] **Step 3: Implementar**

Crear `web/src/components/composicion/PanelAgente.tsx`:

```tsx
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { chatComposicionStream } from "@/api/composicion";
import AvatarIngeniero, { type EstadoAvatar } from "./AvatarIngeniero";
import type {
  CambioAgente,
  ComponentePropuesto,
  RespuestaAgente,
} from "@/lib/tipos";

type EstadoBloque = "pendiente" | "aplicando" | "aplicado" | "descartado";

interface Entrada {
  id: number;
  rol: "usuario" | "agente";
  texto: string;
  respuesta?: RespuestaAgente;
  /** El mensaje del usuario que originó esta respuesta: viaja como rastro al aplicar. */
  instruccion?: string;
  estado?: EstadoBloque;
  conflictos?: string[];
}

interface Props {
  corridaId: number;
  seq: number;
  /** La tabla tal como está en pantalla, sin guardar incluido: es lo que ve el agente. */
  componentes: ComponentePropuesto[];
  /** Motivo por el que el agente no está disponible, o null. */
  deshabilitado: string | null;
  /** Aplica los cambios (tabla + PUT). Devuelve los conflictos, si hubo. */
  onAplicar: (cambios: CambioAgente[], instruccion: string) => Promise<string[]>;
}

const num = (n: number) =>
  Number.isFinite(n) ? n.toLocaleString("es-CO", { maximumFractionDigits: 4 }) : "—";

const SIGNO = { agregar: "+", modificar: "~", quitar: "−" } as const;

let proximoId = 1;

/** Chat con el agente de composición. El historial vive acá (efímero: recargar lo
 *  borra); lo que queda es cada cambio aplicado, como versión del expediente. */
export default function PanelAgente({
  corridaId, seq, componentes, deshabilitado, onAplicar,
}: Props) {
  const [hilo, setHilo] = useState<Entrada[]>([]);
  const [texto, setTexto] = useState("");
  const [estado, setEstado] = useState<EstadoAvatar>("espera");
  const [linea, setLinea] = useState("");
  const [aviso, setAviso] = useState<string | null>(null);
  const [plegado, setPlegado] = useState(false);
  const montado = useRef(true);
  const temporizador = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    montado.current = true;
    return () => {
      montado.current = false;
      if (temporizador.current) clearTimeout(temporizador.current);
    };
  }, []);

  const ocupado = estado === "pensando" || estado === "buscando";
  const visible: EstadoAvatar = deshabilitado ? "deshabilitado" : estado;

  function marcar(id: number, cambios: Partial<Entrada>) {
    setHilo((h) => h.map((e) => (e.id === id ? { ...e, ...cambios } : e)));
  }

  async function enviar() {
    const t = texto.trim();
    if (!t || ocupado || deshabilitado) return;
    const previo = hilo;
    const conMensaje: Entrada[] = [...hilo, { id: proximoId++, rol: "usuario", texto: t }];
    setHilo(conMensaje);
    setTexto("");
    setAviso(null);
    setEstado("pensando");
    setLinea("Pensando…");
    // Un objeto y no dos `let`: TypeScript no ve las asignaciones dentro del callback
    // y estrecharía las variables a `null` después del `await`.
    const res: { respuesta: RespuestaAgente | null; fallo: string | null } =
      { respuesta: null, fallo: null };
    try {
      await chatComposicionStream(
        corridaId, seq,
        { mensajes: conMensaje.map(({ rol, texto: x }) => ({ rol, texto: x })), componentes },
        (ev) => {
          if (!montado.current) return;
          const d = (ev.data ?? {}) as { consulta?: string; motivo?: string; detail?: string };
          if (ev.event === "pensando") {
            setEstado("pensando");
            setLinea("Pensando…");
          } else if (ev.event === "buscando") {
            setEstado("buscando");
            setLinea(`Buscando «${d.consulta ?? ""}» en el catálogo…`);
          } else if (ev.event === "respuesta") {
            res.respuesta = ev.data as RespuestaAgente;
          } else if (ev.event === "bloqueado" || ev.event === "error") {
            res.fallo = d.motivo ?? d.detail ?? "No pude responder, vuelve a intentar.";
          }
        });
    } catch (e) {
      res.fallo = e instanceof Error ? e.message : "No pude responder, vuelve a intentar.";
    }
    if (!montado.current) return;
    setLinea("");
    const r = res.respuesta;
    if (r) {
      setHilo([...conMensaje, {
        id: proximoId++, rol: "agente", texto: r.texto, respuesta: r, instruccion: t,
        estado: r.cambios.length > 0 ? "pendiente" : undefined,
      }]);
      setEstado("lista");
      temporizador.current = setTimeout(() => {
        if (montado.current) setEstado("espera");
      }, 1500);
    } else {
      // El mensaje vuelve a la caja para corregirlo: no se queda en el hilo un
      // mensaje que el agente nunca recibió.
      setHilo(previo);
      setTexto(t);
      setAviso(res.fallo ?? "El agente no respondió. Vuelve a intentar.");
      setEstado("error");
    }
  }

  async function aplicar(e: Entrada) {
    if (!e.respuesta || e.estado !== "pendiente") return;
    marcar(e.id, { estado: "aplicando" });
    try {
      const conflictos = await onAplicar(e.respuesta.cambios, e.instruccion ?? "");
      if (montado.current) marcar(e.id, { estado: "aplicado", conflictos });
    } catch (err) {
      if (!montado.current) return;
      marcar(e.id, { estado: "pendiente" });
      setAviso(err instanceof Error ? err.message : "No se pudieron aplicar los cambios.");
    }
  }

  return (
    <aside
      aria-label="Agente de composición"
      className="flex flex-col gap-2 border-l pl-3 lg:sticky lg:top-3"
    >
      <div className="flex items-center gap-2">
        <AvatarIngeniero estado={visible} />
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold text-foreground">Agente</p>
          <p aria-live="polite" className="truncate text-[11px] text-muted-foreground">
            {deshabilitado ? "No disponible" : linea || "Listo para ayudarte"}
          </p>
        </div>
        <button
          type="button"
          aria-expanded={!plegado}
          className="text-[11px] text-muted-foreground underline underline-offset-2 hover:text-foreground"
          onClick={() => setPlegado((v) => !v)}
        >
          {plegado ? "Mostrar" : "Plegar"}
        </button>
      </div>

      {!plegado && (
        <>
          {deshabilitado && (
            <p className="border-l-2 border-revisar bg-revisar-surface px-2 py-1 text-xs text-revisar">
              {deshabilitado}
            </p>
          )}

          <div className="flex max-h-[55vh] flex-col gap-2 overflow-y-auto">
            {hilo.length === 0 && !deshabilitado && (
              <p className="text-xs text-muted-foreground">
                {"Cuéntame qué lleva esta actividad o qué quieres cambiar de la tabla. "
                  + "Por ejemplo: «agrega una cuadrilla de un oficial y dos ayudantes» o "
                  + "«busca una mano de obra que tenga licencia de soldador». Yo propongo "
                  + "y tú decides si lo aplicas. No veo precios."}
              </p>
            )}
            {hilo.map((e) => (
              <div key={e.id} className={e.rol === "usuario" ? "self-end text-right" : ""}>
                <p
                  className={
                    "whitespace-pre-wrap text-xs "
                    + (e.rol === "usuario"
                      ? "rounded bg-muted px-2 py-1 text-foreground"
                      : "text-foreground")
                  }
                >
                  {e.texto}
                </p>
                {e.respuesta && e.respuesta.cambios.length > 0 && (
                  <ul className="mt-1 flex flex-col gap-0.5 border-l-2 border-info pl-2">
                    {e.respuesta.cambios.map((c, i) => {
                      const info = e.respuesta!.catalogo[c.codigo];
                      const actual = componentes.find((x) => x.codigo === c.codigo);
                      const rend = c.op === "modificar" && actual && c.componente
                        ? `${num(actual.rendimiento)} → ${num(c.componente.rendimiento)}`
                        : c.componente ? num(c.componente.rendimiento) : "";
                      const ref = c.componente?.referencias[0];
                      return (
                        <li key={`${c.codigo}@@${i}`} className="font-mono text-[11px] text-foreground">
                          {SIGNO[c.op]} {c.codigo} {info?.nombre ?? ""} {info?.unidad ?? ""} {rend}
                          {ref && (
                            <span className="text-muted-foreground"> (antecedente APU {ref.apu_codigo})</span>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                )}
                {e.respuesta && e.respuesta.descartados.length > 0 && (
                  <ul className="mt-1 flex flex-col gap-0.5">
                    {e.respuesta.descartados.map((d, i) => (
                      <li key={`${d.codigo}@@${i}`} className="text-[11px] text-revisar">
                        ⚠ {d.codigo}: {d.motivo}
                      </li>
                    ))}
                  </ul>
                )}
                {e.estado === "pendiente" && (
                  <div className="mt-1 flex gap-2">
                    <Button size="sm" onClick={() => void aplicar(e)}>Aplicar</Button>
                    <Button size="sm" variant="outline"
                            onClick={() => marcar(e.id, { estado: "descartado" })}>
                      Descartar
                    </Button>
                  </div>
                )}
                {e.estado === "aplicando" && (
                  <p className="mt-1 text-[11px] text-info">Aplicando…</p>
                )}
                {e.estado === "aplicado" && (
                  <p className="mt-1 text-[11px] text-info">Aplicado: la tabla se revalidó sin IA.</p>
                )}
                {e.estado === "descartado" && (
                  <p className="mt-1 text-[11px] text-muted-foreground">Descartado.</p>
                )}
                {(e.conflictos ?? []).map((c, i) => (
                  <p key={i} className="text-[11px] text-revisar">⚠ {c}</p>
                ))}
              </div>
            ))}
          </div>

          {aviso && (
            <p className="border-l-2 border-destructive bg-destructive-surface px-2 py-1 text-xs text-destructive">
              {aviso}
            </p>
          )}

          <div className="flex flex-col gap-1">
            <textarea
              aria-label="Mensaje para el agente"
              rows={3}
              value={texto}
              disabled={!!deshabilitado || ocupado}
              placeholder="Escribe tu instrucción… (Enter envía, Shift+Enter baja de línea)"
              className="w-full resize-y rounded border border-border bg-transparent px-2 py-1 text-xs outline-none focus-visible:border-ring disabled:opacity-50"
              onChange={(ev) => setTexto(ev.target.value)}
              onKeyDown={(ev) => {
                if (ev.key === "Enter" && !ev.shiftKey) {
                  ev.preventDefault();
                  void enviar();
                }
              }}
            />
            <div className="flex justify-end">
              <Button size="sm" disabled={!!deshabilitado || ocupado || !texto.trim()}
                      onClick={() => void enviar()}>
                {ocupado ? "Esperando…" : "Enviar"}
              </Button>
            </div>
          </div>
        </>
      )}
    </aside>
  );
}
```

- [ ] **Step 4: Correr y ver que pasan**

Run: `cd web && npx vitest run src/components/composicion/PanelAgente.test.tsx`
Expected: PASS (5)

- [ ] **Step 5: Commit**

```bash
git add web/src/components/composicion/PanelAgente.tsx web/src/components/composicion/PanelAgente.test.tsx
git commit -m "feat(web): panel de chat con el agente de composicion

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Montar el panel en la mesa

**Files:**
- Modify: `web/src/pages/Composicion.tsx`
- Modify: `web/src/pages/Composicion.test.tsx`

- [ ] **Step 1: Escribir los tests que fallan**

En `web/src/pages/Composicion.test.tsx`:

1. Debajo de `const generarComposicionStream = vi.fn();` agregar:
```ts
const chatComposicionStream = vi.fn();
```
dentro del factory de `vi.mock("@/api/composicion", () => ({ ... }))` agregar:
```ts
  chatComposicionStream: (...a: unknown[]) => chatComposicionStream(...a),
```
y en `beforeEach` agregar `chatComposicionStream.mockReset();`

2. Agregar al final del archivo:

```tsx
type OnEvento = (e: { event: string; data: unknown }) => void;

function respuestaCon(cambio: unknown, texto = "Listo.") {
  return async (_i: number, _s: number, _c: unknown, onEvent: OnEvento) => {
    onEvent({ event: "respuesta", data: {
      texto, cambios: [cambio], descartados: [], catalogo: {}, modelo: "m",
      prompt_version: "chat/v1" } });
  };
}

test("aplicar desde el agente guarda la tabla con el cambio y la instrucción", async () => {
  getComposicion.mockResolvedValue({ ...vista(version()), ia_disponible: true });
  guardarComposicion.mockResolvedValue({ ...vista(version()), ia_disponible: true });
  const nuevo = { ...COMPONENTE, codigo: "8801", rendimiento: 0.5 };
  chatComposicionStream.mockImplementation(
    respuestaCon({ op: "agregar", codigo: "8801", componente: nuevo }));
  montar();
  const caja = await screen.findByRole("textbox", { name: /mensaje para el agente/i });
  fireEvent.change(caja, { target: { value: "agrega un oficial" } });
  fireEvent.click(boton(/enviar/i));
  fireEvent.click(await screen.findByRole("button", { name: /^aplicar$/i }));
  await waitFor(() => expect(guardarComposicion).toHaveBeenCalledWith(
    1, 3, 2, [COMPONENTE, nuevo], false, "agrega un oficial"));
});

test("sin IA en el servidor el panel queda apagado con el motivo", async () => {
  getComposicion.mockResolvedValue({ ...vista(version()), ia_disponible: false });
  montar();
  expect(await screen.findByText(/ANTHROPIC_API_KEY/)).toBeTruthy();
});

test("mesa vacía: aplicar arranca en la versión 0", async () => {
  getComposicion.mockResolvedValue({ ...vista(null, {}), ia_disponible: true });
  guardarComposicion.mockResolvedValue({ ...vista(version()), ia_disponible: true });
  const nuevo = { ...COMPONENTE, codigo: "8801" };
  chatComposicionStream.mockImplementation(
    respuestaCon({ op: "agregar", codigo: "8801", componente: nuevo }));
  montar();
  const caja = await screen.findByRole("textbox", { name: /mensaje para el agente/i });
  fireEvent.change(caja, { target: { value: "arma una cuadrilla" } });
  fireEvent.click(boton(/enviar/i));
  fireEvent.click(await screen.findByRole("button", { name: /^aplicar$/i }));
  await waitFor(() => expect(guardarComposicion).toHaveBeenCalledWith(
    1, 3, 0, [nuevo], false, "arma una cuadrilla"));
});
```

- [ ] **Step 2: Correr y ver que fallan**

Run: `cd web && npx vitest run src/pages/Composicion.test.tsx`
Expected: FAIL en los 3 nuevos (no hay caja de mensaje); los viejos siguen pasando.

- [ ] **Step 3: Implementar**

En `web/src/pages/Composicion.tsx`:

1. Imports, después de `import { BuscadorInsumo } from "@/components/autoria/DialogoAgregarApu";`:
```tsx
import PanelAgente from "@/components/composicion/PanelAgente";
import { aplicarCambios } from "@/lib/cambiosAgente";
```
y agregar `CambioAgente,` al `import type { ... } from "@/lib/tipos";`.

2. Justo antes de `// ─── render ───` (después de la función `aprobar`), agregar:

```tsx
  /** Aplica una propuesta del agente: la tabla de AHORA (con lo que hayas editado
   *  sin guardar, que es lo que vio el agente) más los cambios, guardada por el PUT
   *  de siempre con la instrucción como rastro. Sin expediente (mesa vacía) arranca
   *  en la versión 0. Devuelve los conflictos para que el panel los muestre. */
  async function aplicarDelAgente(
    cambios: CambioAgente[], instruccion: string,
  ): Promise<string[]> {
    const { componentes: nuevos, conflictos } = aplicarCambios(componentesDe(filas), cambios);
    const v = await guardarComposicion(
      corridaId, linea, vigente?.version ?? 0, nuevos, supuestosOk, instruccion);
    if (montado.current) adoptar(v);
    toast.success("Cambios del agente aplicados. La propuesta se revalidó sin IA.");
    return conflictos;
  }

  const motivoSinAgente: string | null =
    !vista?.ia_disponible
      ? "El agente necesita ANTHROPIC_API_KEY en el servidor."
      : congelada
        ? "La corrida está congelada: el agente no puede proponer cambios."
        : !puedeEditar
          ? "Tu rol no permite cambiar esta composición."
          : vigente?.estado === "aprobada"
            ? "Esta composición ya se aprobó: el APU está en la biblioteca."
            : null;
```

(`vigente`, `congelada`, `puedeEditar`, `supuestosOk`, `filas`, `componentesDe`, `adoptar` y `montado` ya existen arriba en el componente.)

3. Layout. Reemplazar:
```tsx
            {vigente && ` · ${vigente.estado} v${vigente.version}`}
          </p>
        </div>
      </div>
```
por:
```tsx
            {vigente && ` · ${vigente.estado} v${vigente.version}`}
          </p>
        </div>
      </div>

      {/* La mesa a la izquierda y el agente a la derecha; en pantallas angostas el
          agente pasa debajo. */}
      <div className="grid items-start gap-3 lg:grid-cols-[minmax(0,1fr)_360px]">
      <div className="flex min-w-0 flex-col gap-3">
```

Y reemplazar:
```tsx
        </>
      )}

      {identidad && actividad && (
```
por:
```tsx
        </>
      )}
      </div>

      <PanelAgente
        corridaId={corridaId}
        seq={linea}
        componentes={componentes}
        deshabilitado={motivoSinAgente}
        onAplicar={aplicarDelAgente}
      />
      </div>

      {identidad && actividad && (
```

(`componentes` es la derivada `componentesDe(filas)` que ya existe en el componente.)

- [ ] **Step 4: Correr los tests de la página**

Run: `cd web && npx vitest run src/pages/Composicion.test.tsx`
Expected: PASS (viejos y nuevos)

Si un test viejo falla por un botón duplicado (p. ej. un `getByRole("button", { name: /.../ })` que ahora también encuentra uno del panel), acotar ese test viejo con el nombre exacto del botón de la mesa — sin cambiar comportamiento.

- [ ] **Step 5: Suite completa del frontend y build**

Run: `cd web && npx vitest run`
Expected: PASS

Run: `cd web && npm run build`
Expected: build sin errores.

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/Composicion.tsx web/src/pages/Composicion.test.tsx
git commit -m "feat(web): el agente vive al lado de la mesa de composicion

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Documentación

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/pendientes-agente-composicion.md`

- [ ] **Step 1: CLAUDE.md**

1. En la tabla de `apu_tool/dominio/`, después de la fila de `composicion_agente.py`:
```
| `composicion_chat.py`    | chat con el agente en la mesa de composición: herramientas de búsqueda (solo lectura, sin dinero) y bucle de tool use con tope; propone, no escribe |
```
2. En el diagrama de "Arquitectura (flujo)", después de la línea de "fila sin APU ──► composición con IA…" y su continuación, agregar:
```
mesa de composición ──► chat con el agente (busca, sin dinero) ──► propone cambios ──► aplica usuario (PUT de la mesa)
```
3. En "Datos", al final del párrafo de **Expediente de composición**, agregar:
```
  **Chat con el agente (2026-11).** En la mesa hay un panel de chat (`dominio/composicion_chat.py`,
  `POST .../composicion/{seq}/chat`, rol `editor`, SSE). El agente busca en el catálogo
  (`buscar_insumos`, `buscar_apus`, tope de 4 por mensaje) y **propone** cambios
  (agregar/modificar/quitar); la persona los aplica y eso es el `PUT` de siempre con
  `instruccion`, que deja `motivo="chat: …"`, `modelo=config.AI_MODEL` y
  `prompt_version="chat/v1"` (los pone el servidor). El chat **no persiste nada** y su
  historial vive en el navegador; por eso el servidor revisa **todos** los mensajes —
  también los "del agente"— con `privacy.texto_con_dinero` y responde `bloqueado` sin
  llamar a la IA. Con la mesa vacía, el primer `PUT` va con `version_base = 0` y crea la
  versión siguiente al historial crudo (el seq se reusa).
```
4. En "No hacer", agregar:
```
- No le mandes al agente del chat texto libre de la mesa (`justificacion`, `hipotesis`):
  una persona pudo escribir un monto ahí. `privacy.componente_mesa_to_dict` copia solo los
  campos estructurados, a propósito.
- No le quites al detector de dinero del chat (`privacy.texto_con_dinero`) los mensajes
  "del agente": el historial lo manda el cliente. Y no le agregues "vale" (es "de
  acuerdo" en Colombia) ni "peso" en singular (es peso físico).
- No cierres el bucle del chat con `tool_choice` forzado: los modelos nuevos lo rechazan
  con 400. El tope apaga las herramientas con `{"type": "none"}` sin sacarlas de `tools`.
```

- [ ] **Step 2: Backlog**

En `docs/pendientes-agente-composicion.md`, reemplazar el bloque del 2026-11-18 (las dos líneas que enlazan el diseño del chat) por:
```
> **2026-11-19:** chat con el agente en la mesa — implementado en la rama
> `feat/chat-agente-composicion`. Diseño: `docs/superpowers/specs/2026-11-18-chat-agente-composicion-design.md`.
> Plan: `docs/superpowers/plans/2026-11-19-chat-agente-composicion.md`. Falta: navegador
> y smoke con la API real (mismo bloqueo que el punto 1).
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/pendientes-agente-composicion.md
git commit -m "docs: chat con el agente en CLAUDE.md y en el backlog

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 15: Verificación final

- [ ] **Step 1: Suites completas**

Run: `python -m pytest tests/ -q`
Expected: todo verde.

Run: `cd web && npx vitest run && npm run build`
Expected: todo verde, build limpio.

- [ ] **Step 2: Navegador (antes de cualquier push)**

Levantar la app en local (`scripts/servidor_local.py`, o la receta de la memoria `web-local-auth-receta`: `SUPABASE_URL` + `APU_ADMIN_EMAILS`) y abrir una fila sin APU → mesa. Verificar a ojo:
- el panel sale a la derecha en pantalla ancha y debajo en angosta;
- el avatar en `espera` respira y parpadea; sin `ANTHROPIC_API_KEY`, gris y con el motivo;
- con `prefers-reduced-motion` (DevTools → Rendering → Emulate CSS media feature) no se mueve;
- un mensaje con "$45.000" vuelve a la caja con el aviso, sin llamar a la IA;
- el dibujo se ve bien en tema claro y oscuro.

Si hay que ajustar coordenadas del SVG, se ajustan en `AvatarIngeniero.tsx` y se vuelve a correr su test.

- [ ] **Step 3: Smoke con la API real (necesita `ANTHROPIC_API_KEY` y OK del usuario: gasta créditos)**

Tres actividades de familias distintas. Por cada una, anotar: si los cambios propuestos son correctos, cuántas búsquedas usó por mensaje, y el `usage` del log del servidor (`chat composición: entrada=… salida=…`).

- [ ] **Step 4: Reportar al usuario**

Resumen de lo hecho, resultados de las suites y lo que quedó sin verificar. **No** hacer push a master sin su OK explícito.
