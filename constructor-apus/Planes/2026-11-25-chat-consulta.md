> Espejo automático — no editar aquí. Fuente: `docs/superpowers/plans/2026-11-25-chat-consulta.md`

# Chat de consulta — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un chat disponible en toda la app que responde preguntas de precios de insumos, costos de APUs y totales de corridas o capítulos, sin que la IA vea un solo monto.

**Architecture:** La IA usa herramientas de búsqueda que devuelven nombres y referencias (`ref`), sin dinero, y redacta con marcadores `{{campo:tipo:id}}`. Cuando el modelo termina, `servicio/consulta.py` reemplaza cada marcador por la cifra que calculan `PricingEngine` y `vista_corrida`, las mismas funciones de la pantalla. El historial vuelve al servidor con la versión con marcadores (`crudo`), nunca con las cifras.

**Tech Stack:** Python 3 / FastAPI / SSE, Anthropic SDK (tool use, pensamiento adaptativo), React + TypeScript + vitest.

**Spec:** `docs/superpowers/specs/2026-11-25-chat-consulta-design.md`. Léelo antes de empezar.

**Reglas del repo que aplican (CLAUDE.md):**

- Invariante #1: nada con dinero hacia la IA. Todo resultado de herramienta pasa por `privacy.safe_json`, y una `PrivacyViolation` nunca se traga.
- Español de Colombia en mensajes, tuteando.
- Rama `feat/chat-consulta`, ya creada. **No hagas push** sin aprobación explícita.
- Corre `python -m pytest tests/ -q` antes de dar una tarea por terminada.
- Frontend: verifica con `npm run build` (incluye `tsc -b`), no con `tsc --noEmit`.

---

## Mapa de archivos

| Archivo | Responsabilidad |
|---|---|
| `apu_tool/dominio/privacy.py` (modificar) | `cifra_monetaria()` y los helpers `*_consulta_to_dict` |
| `apu_tool/dominio/alertas.py` (modificar) | constante pública `CALIDADES_CON_ALERTA` |
| `apu_tool/dominio/ai_assist.py` (modificar) | prompt, herramientas y `turno_consulta`; helper `_turno` compartido con `turno_chat` |
| `apu_tool/dominio/consulta_chat.py` (crear) | `HerramientasConsulta`, `MARCADOR`, candado de cifras inventadas, bucle `conversar` |
| `apu_tool/servicio/consulta.py` (crear) | reemplazo de marcadores (`resolver`) y `chat_stream` |
| `apu_tool/servicio/esquemas.py` (modificar) | `ChatConsultaIn` |
| `apu_tool/servicio/rutas.py` (modificar) | `POST /api/consulta/chat` |
| `tests/chat_falso.py` (modificar) | `_pedir_consulta_al_sdk` en `AdvisorGuion`, `resp_texto`, `resp_llamada` |
| `tests/consulta_base.py` (crear) | base de prueba compartida (insumos, APUs, carpetas, corridas con capítulos) |
| `tests/test_privacy_consulta.py` (crear) | `cifra_monetaria` y helpers |
| `tests/test_consulta_advisor.py` (crear) | `turno_consulta` |
| `tests/test_consulta_chat_herramientas.py` (crear) | las 4 herramientas |
| `tests/test_consulta_chat_motor.py` (crear) | el bucle |
| `tests/test_consulta_resolver.py` (crear) | el reemplazo |
| `tests/test_api_consulta_chat.py` (crear) | el endpoint |
| `web/src/lib/tipos.ts` (modificar) | `RespuestaConsulta` |
| `web/src/api/consulta.ts` (crear) | `chatConsultaStream` |
| `web/src/components/consulta/ChatConsulta.tsx` (crear) | botón flotante y panel |
| `web/src/components/consulta/ChatConsulta.test.tsx` (crear) | pruebas del panel |
| `web/src/components/Layout.tsx` (modificar) | monta `ChatConsulta` |
| `web/src/components/Layout.test.tsx` (modificar) | mock de `@/api/consulta` |
| `scripts/smoke_chat_consulta.py` (crear) | smoke real con API key |
| `CLAUDE.md` (modificar) | documentación de la feature |

---

### Task 1: `cifra_monetaria` y los helpers de privacidad

**Files:**
- Modify: `apu_tool/dominio/privacy.py` (al final del archivo, antes de `class PrivacyViolation`)
- Test: `tests/test_privacy_consulta.py`

- [ ] **Step 1: Escribe las pruebas que fallan**

```python
"""Frontera de privacidad del chat de consulta."""
from types import SimpleNamespace

import pytest

from apu_tool.dominio import privacy


@pytest.mark.parametrize("texto", [
    "vale $45.000",
    "unos 45.000",
    "1,250,000 en total",
    "cerca de 3 millones",
    "como 200 mil",
    "45k",
    "en pesos colombianos 12",
    "USD 30",
])
def test_cifra_monetaria_ataja_las_senales_fuertes(texto):
    assert privacy.cifra_monetaria(texto)


@pytest.mark.parametrize("texto", [
    "El costo de la Calle 13 es ",                # número de proyecto junto a «costo»
    "Contractual de la corrida 12: ",
    "Tubería PVC de 6 pulgadas",
    "Concreto de 3000 psi",
    "Hay 3 coincidencias para «tubería»",
    "8 horas de cuadrilla, 4 kg de alambre",
    "3 milímetros",
])
def test_cifra_monetaria_deja_pasar_texto_normal_del_agente(texto):
    assert privacy.cifra_monetaria(texto) is None


def test_helpers_de_consulta_no_llevan_dinero():
    ins = SimpleNamespace(id=7, codigo="8001", nombre="TUBERIA PVC", unidad="ML",
                          grupo="MAT", precio=35000, fuente_precio="COSTO INTERNO")
    meta = SimpleNamespace(id=3, nombre="", archivo="calle13.xlsx",
                           estado="en_revision", modo="activa")
    salida = [privacy.insumo_consulta_to_dict(ins),
              privacy.apu_consulta_to_dict("A1", "MEZCLA", "DIURNO"),
              privacy.corrida_consulta_to_dict(meta, "CALLE 13"),
              privacy.capitulo_consulta_to_dict(3, "2", "REDES HUMEDAS", 4)]
    privacy.assert_no_money(salida)
    texto = privacy.safe_json(salida)
    assert "35000" not in texto and "COSTO INTERNO" not in texto
    assert [s["ref"] for s in salida] == [
        "insumo:7", "apu:A1|DIURNO", "corrida:3", "capitulo:3:2"]
    assert salida[2]["nombre"] == "calle13"          # sin alias: el archivo sin extensión
```

- [ ] **Step 2: Confirma que fallan**

Run: `python -m pytest tests/test_privacy_consulta.py -q`
Expected: FAIL con `AttributeError: module 'apu_tool.dominio.privacy' has no attribute 'cifra_monetaria'`

- [ ] **Step 3: Implementa**

Agrega a `apu_tool/dominio/privacy.py`, justo antes de `class PrivacyViolation`:

```python
# --------------------------------------------------------------- chat de consulta
# Un número pegado a "mil"/"millones"/"k". El lookahead exige que no siga una letra:
# así "3 milímetros" y "4 kg" pasan.
_CIFRA_MILES_PALABRA = re.compile(
    r"\d[\d.,]*\s*(?:mil(?:es)?|mill[oó]n(?:es)?|k)(?![^\W\d_])", re.IGNORECASE)


def cifra_monetaria(texto: str) -> Optional[str]:
    """El fragmento con un monto si `texto` trae uno escrito, o None.

    Más ANGOSTA que `texto_con_dinero` a propósito: solo señales fuertes (símbolo o
    moneda, separador de miles, número pegado a mil/millones). Se usa sobre el texto
    del AGENTE de consulta, que nombra proyectos con números al lado de palabras de
    dinero («el costo de la Calle 13: {{…}}»); ahí la ventana de `texto_con_dinero`
    omitiría casi toda respuesta. Un precio inventado se escribe con símbolo o con
    miles, y eso es lo que esto ataja. Los mensajes del USUARIO siguen pasando por
    `texto_con_dinero` completo.
    """
    t = texto or ""
    for patron in (_SENAL_MONEDA, _MILES, _MILES_COMA, _CIFRA_MILES_PALABRA):
        m = patron.search(t)
        if m:
            return _alrededor(t, m)
    return None


def insumo_consulta_to_dict(ins) -> dict[str, Any]:
    """Un resultado de `buscar_insumos` del chat de consulta. `ins` LLEVA precio: se
    copia campo por campo. El `ref` va por id porque 652 códigos son de dos insumos."""
    return {"ref": f"insumo:{ins.id}", "insumo_codigo": ins.codigo,
            "insumo_nombre": ins.nombre, "unidad": ins.unidad, "grupo": ins.grupo}


def apu_consulta_to_dict(codigo: str, nombre: str, turno: str) -> dict[str, Any]:
    return {"ref": f"apu:{codigo}|{turno}", "codigo": codigo, "nombre": nombre,
            "turno": turno}


def corrida_consulta_to_dict(meta, carpeta: Optional[str]) -> dict[str, Any]:
    """`meta` es un `CorridaMeta`; NO se vuelca (trae `plan_json`/`origen` con dinero)."""
    nombre = meta.nombre or str(meta.archivo).rsplit(".", 1)[0]
    return {"ref": f"corrida:{meta.id}", "nombre": nombre, "carpeta": carpeta,
            "estado": meta.estado, "modo": meta.modo}


def capitulo_consulta_to_dict(corrida_id: int, codigo: str, nombre: str,
                              actividades: int) -> dict[str, Any]:
    return {"ref": f"capitulo:{corrida_id}:{codigo}", "codigo": codigo,
            "nombre": nombre, "actividades": actividades}
```

`re`, `Optional`, `Any`, `_SENAL_MONEDA`, `_MILES`, `_MILES_COMA` y `_alrededor` ya existen en el módulo.

- [ ] **Step 4: Confirma que pasan**

Run: `python -m pytest tests/test_privacy_consulta.py tests/test_privacy.py tests/test_privacy_chat.py -q`
Expected: PASS. Si alguno de los casos de «deja pasar» falla, **no** cambies `_SENAL_MONEDA`, que comparte el chat de la mesa: ajusta solo `_CIFRA_MILES_PALABRA`.

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/privacy.py tests/test_privacy_consulta.py
git commit -m "feat(consulta): cifra_monetaria y helpers sin dinero para el chat de consulta"
```

---

### Task 2: `CALIDADES_CON_ALERTA` en alertas

**Files:**
- Modify: `apu_tool/dominio/alertas.py:14-21`
- Test: `tests/test_privacy_consulta.py` (se agrega una prueba)

- [ ] **Step 1: Escribe la prueba que falla**

Agrega al final de `tests/test_privacy_consulta.py`:

```python
def test_calidades_con_alerta_cubre_los_cruces_que_alertan():
    from apu_tool.dominio.alertas import CALIDADES_CON_ALERTA, _MOTIVO_CRUCE
    from apu_tool.nucleo.models import CALIDAD_SIN_PRECIO_LISTA
    assert set(_MOTIVO_CRUCE) <= CALIDADES_CON_ALERTA
    assert CALIDAD_SIN_PRECIO_LISTA in CALIDADES_CON_ALERTA
    assert "exacto" not in CALIDADES_CON_ALERTA
```

- [ ] **Step 2: Confirma que falla**

Run: `python -m pytest tests/test_privacy_consulta.py -q -k calidades`
Expected: FAIL con `ImportError: cannot import name 'CALIDADES_CON_ALERTA'`

- [ ] **Step 3: Implementa**

En `apu_tool/dominio/alertas.py`, justo después del diccionario `_MOTIVO_CRUCE`:

```python
# Las calidades de cruce que hacen alertar a un componente. Pública para el chat de
# consulta (`servicio/consulta.py`), que marca un APU incompleto sin repetir la lista.
CALIDADES_CON_ALERTA = frozenset(_MOTIVO_CRUCE) | {CALIDAD_SIN_PRECIO_LISTA}
```

- [ ] **Step 4: Confirma que pasa**

Run: `python -m pytest tests/test_privacy_consulta.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/alertas.py tests/test_privacy_consulta.py
git commit -m "feat(consulta): CALIDADES_CON_ALERTA publica en alertas"
```

---

### Task 3: `turno_consulta` en el advisor

**Files:**
- Modify: `apu_tool/dominio/ai_assist.py` (sección chat, líneas ~238-480)
- Modify: `tests/chat_falso.py`
- Test: `tests/test_consulta_advisor.py`

- [ ] **Step 1: Amplía el doble de prueba**

En `tests/chat_falso.py`, agrega después de `resp_final`:

```python
def resp_texto(texto):
    """Respuesta final del chat de CONSULTA: texto plano, sin JSON."""
    return SimpleNamespace(stop_reason="end_turn",
                           content=[SimpleNamespace(type="text", text=texto)],
                           usage=USO)


def resp_llamada(nombre, entrada, id_="c0"):
    """Una respuesta que pide UNA herramienta con una entrada arbitraria."""
    return SimpleNamespace(
        stop_reason="tool_use", usage=USO,
        content=[SimpleNamespace(type="tool_use", id=id_, name=nombre, input=entrada)])
```

Y dentro de `class AdvisorGuion`, agrega el método:

```python
    def _pedir_consulta_al_sdk(self, mensajes, con_herramientas):
        self.llamadas.append({"mensajes": list(mensajes),
                              "con_herramientas": con_herramientas})
        return self.respuestas.pop(0)
```

- [ ] **Step 2: Escribe las pruebas que fallan**

`tests/test_consulta_advisor.py`:

```python
"""La puerta del chat de consulta al SDK. No se llama a la API real."""
from types import SimpleNamespace

import pytest

from apu_tool.dominio import ai_assist
from apu_tool.dominio.ai_assist import ApuAdvisor, IANoDisponible
from apu_tool.dominio.privacy import PrivacyViolation


def _con_cliente_falso():
    capturado = {}
    a = ApuAdvisor(enabled=False)
    a.enabled = True
    a._client = SimpleNamespace(messages=SimpleNamespace(
        create=lambda **kw: capturado.update(kw) or "RESP"))
    return a, capturado


def test_sin_credencial_dice_que_falta_la_llave():
    with pytest.raises(IANoDisponible, match="Consultar al agente necesita ANTHROPIC"):
        ApuAdvisor(enabled=False).turno_consulta([], con_herramientas=True)


def test_dinero_en_los_mensajes_revienta_antes_de_llamar():
    a, capturado = _con_cliente_falso()
    with pytest.raises(PrivacyViolation):
        a.turno_consulta([{"role": "user", "content": [{"costo": 1}]}],
                         con_herramientas=True)
    assert capturado == {}


def test_llama_con_su_prompt_sus_herramientas_y_sin_esquema_json():
    a, capturado = _con_cliente_falso()
    assert a.turno_consulta([{"role": "user", "content": "hola"}],
                            con_herramientas=True) == "RESP"
    assert capturado["system"] == ai_assist._SISTEMA_CONSULTA
    assert capturado["tools"] == ai_assist.HERRAMIENTAS_CONSULTA
    assert capturado["tool_choice"] == {"type": "auto"}
    assert "format" not in capturado["output_config"]


def test_en_el_tope_apaga_las_herramientas_sin_sacarlas():
    a, capturado = _con_cliente_falso()
    a.turno_consulta([{"role": "user", "content": "hola"}], con_herramientas=False)
    assert capturado["tool_choice"] == {"type": "none"}
    assert capturado["tools"] == ai_assist.HERRAMIENTAS_CONSULTA


def test_las_herramientas_son_estrictas_y_son_cuatro():
    nombres = [h["name"] for h in ai_assist.HERRAMIENTAS_CONSULTA]
    assert nombres == ["buscar_insumos", "buscar_apus", "buscar_proyectos", "capitulos"]
    assert all(h["strict"] for h in ai_assist.HERRAMIENTAS_CONSULTA)


def test_el_chat_de_la_mesa_conserva_su_mensaje():
    """Regresión del refactor de `_turno`."""
    with pytest.raises(IANoDisponible, match="Conversar con el agente necesita ANTHROPIC"):
        ApuAdvisor(enabled=False).turno_chat([], con_herramientas=True)
```

- [ ] **Step 3: Confirma que fallan**

Run: `python -m pytest tests/test_consulta_advisor.py -q`
Expected: FAIL con `AttributeError: 'ApuAdvisor' object has no attribute 'turno_consulta'`

- [ ] **Step 4: Implementa el prompt y las herramientas**

En `apu_tool/dominio/ai_assist.py`, después de `MAX_TOKENS_CHAT = 16000`:

```python
# ------------------------------------------------------------ chat de consulta
# `dominio/consulta_chat.py`. La IA entiende la pregunta y escribe MARCADORES; las
# cifras las pone `servicio/consulta.py` cuando el modelo ya terminó. Salida en texto
# plano: no hay nada estructurado que parsear, solo marcadores dentro del texto.
PROMPT_VERSION_CONSULTA = "consulta/v1"   # se sube A MANO al tocar el prompt o las herramientas

_SISTEMA_CONSULTA = """\
Eres el asistente de consulta de costos de una empresa de obra civil. Respondes
preguntas sobre el precio de un insumo, el costo de un APU (análisis de precios
unitarios) de la biblioteca y los totales de una licitación (corrida) o de un
capítulo de una corrida.

NUNCA ves cifras de dinero y NUNCA las escribes. Ni montos, ni el símbolo $, ni las
palabras pesos, mil o millones, ni cálculos. En el lugar de cada cifra escribes un
MARCADOR y el sistema lo reemplaza por el valor real antes de mostrarlo:

  {{<campo>:<ref>}}

donde <ref> es EXACTAMENTE el campo `ref` de un resultado de herramienta que viste en
esta conversación. Campos válidos según el tipo de ref:
  - insumo:...    → precio          ej. {{precio:insumo:812}}
  - apu:...       → costo           ej. {{costo:apu:4859|DIURNO}}
  - corrida:...   → contractual, costo, diferencia, margen
                                    ej. {{contractual:corrida:12}}
  - capitulo:...  → contractual, costo, diferencia, margen
                                    ej. {{costo:capitulo:12:2}}
`diferencia` es contractual menos costo; `margen` es ese mismo margen en porcentaje.
No inventes refs. Si no encontraste lo que te preguntan, dilo.

Herramientas:
- `buscar_insumos(texto)`: insumos del catálogo por palabras del nombre. Exige TODAS
  las palabras: usa dos o tres esenciales ("tuberia pvc", el diámetro como 6"). Si
  trae pocos, quita palabras antes de concluir que no existe.
- `buscar_apus(texto)`: APUs de la biblioteca parecidos. Cuando preguntan por el costo
  de una "actividad", es esto. Si hay versión diurna y nocturna, da las dos.
- `buscar_proyectos(texto)`: proyectos (carpetas) y corridas por nombre. Pasa SOLO el
  nombre ("la cali", "calle 13"), sin palabras como "proyecto" o "licitación".
- `capitulos(corrida_id)`: los capítulos de una corrida. `corrida_id` es el número
  que sigue a "corrida:" en el ref. Úsalo para preguntas como "redes húmedas de la
  Calle 13": primero `buscar_proyectos`, después `capitulos`, y escoges el capítulo
  por su nombre.
Tienes un máximo de 4 búsquedas por mensaje.

Reglas:
- Con varias coincidencias, lista hasta 5 (nombre, unidad y su marcador). Si son
  demasiadas o el proyecto es ambiguo, pregunta cuál.
- Un proyecto puede tener varias corridas (suelen ser versiones de la misma
  licitación): da una línea por corrida y NO digas un total del proyecto.
- Los precios y costos de insumos y APUs son de la lista Principal. El costo interno
  no lleva AIU; el contractual de una licitación del IDU sí lo lleva. Dilo cuando
  compares contractual con costo.
- Si una cifra sale marcada como parcial, no la presentes como definitiva.
- Responde corto, en español de Colombia y tuteando. Texto plano; listas con "- ".
- Solo respondes sobre precios, costos y totales. Para otra cosa, dilo en una línea.
"""

HERRAMIENTAS_CONSULTA = [
    _herramienta("buscar_insumos",
                 "Busca insumos del catálogo por palabras de su nombre. Devuelve hasta "
                 "15 con ref, código, nombre, unidad y grupo. No devuelve precios.",
                 "Palabras cortas del nombre del insumo, p. ej. 'tuberia pvc'."),
    _herramienta("buscar_apus",
                 "Busca APUs de la biblioteca parecidos a un texto, en los dos turnos. "
                 "Devuelve ref, código, nombre y turno. No devuelve costos.",
                 "Descripción corta de la actividad, p. ej. 'mezcla asfaltica'."),
    _herramienta("buscar_proyectos",
                 "Busca proyectos (carpetas) y corridas por nombre. Devuelve las "
                 "corridas de cada proyecto con ref, nombre, carpeta, estado y modo. No "
                 "devuelve totales.",
                 "Solo el nombre del proyecto o la corrida, p. ej. 'calle 13'."),
    {"name": "capitulos",
     "description": "Los capítulos de una corrida: ref, código, nombre y número de "
                    "actividades. No devuelve totales.",
     "strict": True,
     "input_schema": {"type": "object",
                      "properties": {"corrida_id": {
                          "type": "integer",
                          "description": "El número que sigue a 'corrida:' en el ref."}},
                      "required": ["corrida_id"], "additionalProperties": False}},
]
MAX_TOKENS_CONSULTA = 8000
```

- [ ] **Step 5: Implementa `_turno`, `turno_consulta` y `_pedir_consulta_al_sdk`**

En `class ApuAdvisor`, reemplaza **el cuerpo** de `turno_chat` (deja su docstring igual) por una llamada a `_turno`, y agrega los métodos nuevos:

```python
    def _turno(self, accion: str, pedir, mensajes: list, con_herramientas: bool):
        """Guardia común de las dos puertas de chat: sin cliente → IANoDisponible con
        el mensaje de `accion`; dinero → PrivacyViolation FUERA del try (el invariante
        #1 nunca se traga); errores de credencial o saldo → IANoDisponible."""
        if not self.enabled or self._client is None:
            if getattr(self, "_sdk_ausente", False):
                raise IANoDisponible(
                    f"{accion} necesita el SDK de anthropic instalado en el servidor.")
            raise IANoDisponible(f"{accion} necesita ANTHROPIC_API_KEY en el servidor.")
        privacy.assert_no_money(mensajes)
        try:
            return pedir(mensajes, con_herramientas)
        except Exception as exc:
            if credencial_invalida(exc):
                raise IANoDisponible(MSG_CREDENCIAL) from exc
            if sin_saldo(exc):
                raise IANoDisponible(MSG_SIN_SALDO) from exc
            raise

    def turno_chat(self, mensajes: list, *, con_herramientas: bool):
        # ← AQUÍ VA EL DOCSTRING ACTUAL DE turno_chat, COPIADO TAL CUAL (no lo borres).
        return self._turno("Conversar con el agente", self._pedir_chat_al_sdk,
                           mensajes, con_herramientas)

    def turno_consulta(self, mensajes: list, *, con_herramientas: bool):
        """UNA vuelta del bucle del chat de consulta (`dominio/consulta_chat.py`).
        Misma guardia que `turno_chat`; distinto prompt y herramientas."""
        return self._turno("Consultar al agente", self._pedir_consulta_al_sdk,
                           mensajes, con_herramientas)

    def _pedir_consulta_al_sdk(self, mensajes: list, con_herramientas: bool):
        """La llamada pelada. Aparte para que los tests la sustituyan."""
        return self._client.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS_CONSULTA,
            system=_SISTEMA_CONSULTA,
            thinking={"type": "adaptive"},
            output_config={"effort": "low"},
            tools=HERRAMIENTAS_CONSULTA,
            tool_choice={"type": "auto"} if con_herramientas else {"type": "none"},
            messages=mensajes,
            cache_control={"type": "ephemeral"},
        )
```

Los mensajes de `_turno` con `accion="Conversar con el agente"` son **idénticos** a los de hoy. Compruébalo con la prueba de regresión.

- [ ] **Step 6: Confirma que pasan, con las del chat de la mesa**

Run: `python -m pytest tests/test_consulta_advisor.py tests/test_composicion_chat_advisor.py tests/test_composicion_chat_motor.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apu_tool/dominio/ai_assist.py tests/chat_falso.py tests/test_consulta_advisor.py
git commit -m "feat(consulta): turno_consulta en el advisor (prompt consulta/v1, 4 herramientas)"
```

---

### Task 4: Base de prueba compartida

**Files:**
- Create: `tests/consulta_base.py`

- [ ] **Step 1: Escribe la base**

```python
"""Base de prueba del chat de consulta: un catálogo chico, APUs en los dos turnos, y
dos proyectos (carpetas) con corridas. La Calle 13 tiene capítulos y una fila sin APU
en REDES HUMEDAS, para probar lo parcial."""
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import (
    Apu, ApuComponent, CorridaItemRow, CorridaMeta, Insumo, LicitacionItem,
)


def _fila(seq, desc, cantidad, contractual, apu=None, cap=("", "")):
    item = LicitacionItem(str(seq), desc, "M3", cantidad, contractual, "DIURNO",
                          capitulo_codigo=cap[0], capitulo_nombre=cap[1])
    return CorridaItemRow(
        seq=seq, item=item, status="auto" if apu else "new", apu_codigo=apu,
        apu_nombre=apu or "(sin base — armar manual)", unidad="M3", shift="DIURNO",
        origen="historico" if apu else "manual", confianza=0.9 if apu else 0.0,
        explicacion="", componentes=[], candidatos=[])


def _corrida(alm, nombre, carpeta_id, filas):
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-11-25T10:00:00", archivo=f"{nombre}.xlsx",
        turno_def="DIURNO", use_ai=None, estado="en_revision",
        carpeta_id=carpeta_id, nombre=nombre))
    alm.corridas.guardar_items(cid, filas)
    return cid


def almacen_consulta(tmp_path):
    """Devuelve (alm, ids) con ids = {insumo_tubo, insumo_cero, calle13, cali}."""
    from apu_tool import config
    # `Almacen` IGNORA las rutas si hay DATABASE_URL, y esto llama `reset()`. El guard
    # de tests/conftest.py solo protege dentro de pytest: este se defiende solo.
    assert config.db_backend() == "sqlite", "la base de prueba nunca va contra Postgres"
    alm = Almacen(tmp_path / "precios.db", tmp_path / "apus.db",
                  tmp_path / "corridas.db")
    alm.init_schema()
    alm.reset()
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("4279", "CUADRILLA", "HR", "MO", 40000, "PRECIO IDU"),
        Insumo("6092", "HERRAMIENTA MENOR", "GLB", "EQ", 2000, "PRECIO IDU"),
        Insumo("8001", "TUBERIA PVC 6 PULG", "ML", "MAT", 35000, "COSTO INTERNO"),
        Insumo("8002", "TUBERIA PVC 8 PULG", "ML", "MAT", 0, "COSTO INTERNO"),
        # Nombre real del estilo de los 54 que disparan el detector de cifras.
        Insumo("8003", "BASCULA PESO 60.000 KG", "UN", "EQ", 900000, "COSTO INTERNO"),
    ])
    alm.apus.insert_apus([
        Apu("A1", "MEZCLA ASFALTICA MDC-19", "M3", "DIURNO", "PAVIMENTOS"),
        Apu("A1 N", "MEZCLA ASFALTICA MDC-19", "M3", "NOCTURNO", "PAVIMENTOS"),
        Apu("A2", "INSTALACION TUBERIA PVC 6", "ML", "DIURNO", "REDES"),
        Apu("A3", "ACTIVIDAD CON INSUMO HUERFANO", "UN", "DIURNO", "VARIOS"),
    ])
    alm.apus.insert_components([
        ApuComponent("A1", "DIURNO", "4279", "CUADRILLA", "HR", 0.5, 40000),
        ApuComponent("A1", "DIURNO", "6092", "HERRAMIENTA MENOR", "GLB", 1.0, 2000),
        ApuComponent("A1 N", "NOCTURNO", "4279", "CUADRILLA", "HR", 0.6, 40000),
        ApuComponent("A2", "DIURNO", "8001", "TUBERIA PVC 6 PULG", "ML", 1.0, 35000),
        ApuComponent("A3", "DIURNO", "9999", "INSUMO QUE NO EXISTE", "UN", 1.0, 100),
    ])
    calle13 = alm.carpetas.crear("CALLE 13", None)
    cali = alm.carpetas.crear("LA CALI", None)
    cali_sub = alm.carpetas.crear("PRESUPUESTO", cali)
    ids = {
        "insumo_tubo": alm.precios.search_insumos("TUBERIA PVC 6 PULG")[0].id,
        "insumo_cero": alm.precios.search_insumos("TUBERIA PVC 8 PULG")[0].id,
        "calle13": _corrida(alm, "Calle 13 lote SL5", calle13, [
            _fila(1, "MEZCLA ASFALTICA", 10, 30000, "A1", ("1", "PRELIMINARES")),
            _fila(2, "TUBERIA PVC 6", 4, 50000, "A2", ("2", "REDES HUMEDAS")),
            _fila(3, "CAMARA DE INSPECCION", 2, 10000, None, ("2", "REDES HUMEDAS")),
        ]),
        "cali": _corrida(alm, "Cali v1", cali_sub, [
            _fila(1, "MEZCLA ASFALTICA", 1, 25000, "A1")]),
    }
    return alm, ids
```

- [ ] **Step 2: Comprueba que la base se arma**

No la corras con `python -c`: fuera de pytest no está el guard de `DATABASE_URL`. Se comprueba sola en la Tarea 5, que es la primera que la usa. Si ahí falla el armado de la base: si `LicitacionItem` no acepta `capitulo_codigo` como keyword, o si `CorridaMeta` no acepta `carpeta_id`/`nombre`, ajusta los nombres a los de `apu_tool/nucleo/models.py` (`LicitacionItem` línea ~260, `CorridaMeta` línea ~437) antes de seguir.

- [ ] **Step 3: Commit**

```bash
git add tests/consulta_base.py
git commit -m "test(consulta): base de prueba compartida"
```

---

### Task 5: Las herramientas de consulta

**Files:**
- Create: `apu_tool/dominio/consulta_chat.py`
- Test: `tests/test_consulta_chat_herramientas.py`

- [ ] **Step 1: Escribe las pruebas que fallan**

```python
"""Las herramientas del chat de consulta: sin dinero, con refs."""
import pytest

from apu_tool.dominio import privacy
from apu_tool.dominio.consulta_chat import HerramientasConsulta
from tests.consulta_base import almacen_consulta


@pytest.fixture()
def base(tmp_path):
    return almacen_consulta(tmp_path)


def _sin_dinero(r):
    privacy.assert_no_money(r)
    texto = privacy.safe_json(r)
    for prohibido in ("35000", "40000", "COSTO INTERNO", "PRECIO IDU"):
        assert prohibido not in texto


def test_buscar_insumos_trae_refs_por_id_y_sin_precio(base):
    alm, ids = base
    r = HerramientasConsulta(alm).ejecutar("buscar_insumos", {"texto": "tuberia pvc"})
    assert {i["ref"] for i in r["insumos"]} == {
        f"insumo:{ids['insumo_tubo']}", f"insumo:{ids['insumo_cero']}"}
    _sin_dinero(r)


def test_buscar_apus_trae_los_dos_turnos(base):
    alm, _ = base
    r = HerramientasConsulta(alm).ejecutar("buscar_apus", {"texto": "mezcla asfaltica"})
    refs = {a["ref"] for a in r["apus"]}
    assert "apu:A1|DIURNO" in refs and "apu:A1 N|NOCTURNO" in refs
    _sin_dinero(r)


def test_buscar_proyectos_trae_las_corridas_de_subcarpetas(base):
    alm, ids = base
    r = HerramientasConsulta(alm).ejecutar("buscar_proyectos", {"texto": "la cali"})
    assert [p["proyecto"] for p in r["proyectos"]] == ["LA CALI"]
    assert [c["ref"] for c in r["proyectos"][0]["corridas"]] == [f"corrida:{ids['cali']}"]
    assert r["proyectos"][0]["corridas"][0]["carpeta"] == "PRESUPUESTO"
    _sin_dinero(r)


def test_buscar_proyectos_por_numero_de_calle(base):
    alm, ids = base
    r = HerramientasConsulta(alm).ejecutar("buscar_proyectos", {"texto": "calle 13"})
    assert r["proyectos"][0]["corridas"][0]["ref"] == f"corrida:{ids['calle13']}"


def test_buscar_proyectos_encuentra_corridas_por_su_propio_nombre(base):
    alm, ids = base
    r = HerramientasConsulta(alm).ejecutar("buscar_proyectos", {"texto": "lote sl5"})
    assert r["proyectos"] == []
    assert [c["ref"] for c in r["corridas"]] == [f"corrida:{ids['calle13']}"]


def test_buscar_proyectos_sin_palabras_utiles_no_trae_nada(base):
    alm, _ = base
    r = HerramientasConsulta(alm).ejecutar("buscar_proyectos", {"texto": "la de"})
    assert r["proyectos"] == [] and r["corridas"] == []


def test_capitulos_cuenta_actividades_sin_costear(base):
    alm, ids = base
    cid = ids["calle13"]
    r = HerramientasConsulta(alm).ejecutar("capitulos", {"corrida_id": cid})
    assert r["capitulos"] == [
        {"ref": f"capitulo:{cid}:1", "codigo": "1", "nombre": "PRELIMINARES",
         "actividades": 1},
        {"ref": f"capitulo:{cid}:2", "codigo": "2", "nombre": "REDES HUMEDAS",
         "actividades": 2},
    ]
    _sin_dinero(r)


def test_capitulos_de_corrida_inexistente_o_invalida_es_error(base):
    alm, _ = base
    h = HerramientasConsulta(alm)
    assert "error" in h.ejecutar("capitulos", {"corrida_id": 999})
    assert "error" in h.ejecutar("capitulos", {"corrida_id": "x"})


def test_herramienta_desconocida(base):
    alm, _ = base
    assert "error" in HerramientasConsulta(alm).ejecutar("borrar", {"texto": "x"})
```

- [ ] **Step 2: Confirma que fallan**

Run: `python -m pytest tests/test_consulta_chat_herramientas.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'apu_tool.dominio.consulta_chat'`

- [ ] **Step 3: Implementa las herramientas**

`apu_tool/dominio/consulta_chat.py`:

```python
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
from apu_tool.dominio.composicion_chat import (
    MAX_RESULTADOS_APUS, MAX_RESULTADOS_INSUMOS, MIN_RESULTADOS_SIN_SUGERENCIA,
    SUGERENCIA_POCOS,
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
        ids = {p.id for p in proyectos}
        salida = []
        for p in proyectos[:MAX_PROYECTOS]:
            suyas = [m for m in corridas
                     if (pr := proyecto_de(m.carpeta_id)) is not None and pr.id == p.id]
            salida.append({"proyecto": p.nombre,
                           "corridas": [dto(m) for m in suyas[:MAX_CORRIDAS]]})
        sueltas = [m for m in corridas
                   if _casa(terminos, _nombre_corrida(m))
                   and getattr(proyecto_de(m.carpeta_id), "id", None) not in ids]
        return {"consulta": texto, "proyectos": salida,
                "corridas": [dto(m) for m in sueltas[:MAX_CORRIDAS]]}

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
```

- [ ] **Step 4: Confirma que pasan**

Run: `python -m pytest tests/test_consulta_chat_herramientas.py -q`
Expected: PASS. Si `test_buscar_apus_trae_los_dos_turnos` falla porque el `Matcher` no devuelve `A1 N` en NOCTURNO, imprime `Matcher(alm.apus.apu_index()).candidates("mezcla asfaltica", "NOCTURNO")` y ajusta el nombre del APU nocturno en `tests/consulta_base.py`; no cambies el `Matcher`.

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/consulta_chat.py tests/test_consulta_chat_herramientas.py
git commit -m "feat(consulta): herramientas sin dinero (insumos, apus, proyectos, capitulos)"
```

---

### Task 6: Marcadores, candado de cifras y bucle

**Files:**
- Modify: `apu_tool/dominio/consulta_chat.py` (se agrega al final)
- Test: `tests/test_consulta_chat_motor.py`

- [ ] **Step 1: Escribe las pruebas que fallan**

```python
"""El bucle del chat de consulta. El SDK se sustituye (tests/chat_falso.py)."""
import pytest

from apu_tool.dominio import consulta_chat, privacy
from apu_tool.dominio.consulta_chat import (
    MSG_CIFRA_OMITIDA, conversar, limpiar_cifras_inventadas,
)
from apu_tool.dominio.composicion_chat import MSG_OMITIDO
from tests.chat_falso import AdvisorGuion, resp_herramienta, resp_llamada, resp_texto
from tests.consulta_base import almacen_consulta


@pytest.fixture()
def alm(tmp_path):
    return almacen_consulta(tmp_path)[0]


def U(texto):
    return {"rol": "usuario", "texto": texto}


def A(texto):
    return {"rol": "agente", "texto": texto}


def test_busca_y_responde_con_marcadores(alm):
    a = AdvisorGuion([resp_herramienta(("buscar_insumos", "tuberia pvc")),
                      resp_texto("El tubo de 6 vale {{precio:insumo:1}}.")])
    eventos = list(conversar(alm, [U("cuanto vale la tuberia")], a))
    nombres = [e for e, _ in eventos]
    assert nombres == ["pensando", "buscando", "pensando", "respuesta"]
    assert eventos[-1][1]["crudo"] == "El tubo de 6 vale {{precio:insumo:1}}."
    assert eventos[-1][1]["prompt_version"] == "consulta/v1"
    resultado = a.llamadas[1]["mensajes"][-1]["content"][0]["content"]
    assert "TUBERIA PVC" in resultado and "35000" not in resultado


def test_capitulos_recibe_el_id_de_la_corrida(alm):
    a = AdvisorGuion([resp_llamada("capitulos", {"corrida_id": 1}),
                      resp_texto("Listo.")])
    eventos = list(conversar(alm, [U("capitulos de la calle 13")], a))
    assert ("buscando", {"herramienta": "capitulos", "consulta": "corrida 1"}) in eventos


def test_mensaje_del_usuario_con_dinero_bloquea_sin_llamar(alm):
    a = AdvisorGuion([])
    eventos = list(conversar(alm, [U("insumos de mas de $50.000")], a))
    assert eventos[0][0] == "bloqueado" and a.llamadas == []


def test_falso_positivo_conocido_del_detector_queda_fijado(alm):
    """«cuesta» y un número a menos de 3 palabras: se bloquea. Riesgo aceptado en el
    spec; si alguien afloja el detector, esta prueba lo hace notar."""
    a = AdvisorGuion([])
    eventos = list(conversar(alm, [U("cuanto cuesta el apu 4859")], a))
    assert eventos[0][0] == "bloqueado"


def test_mensaje_del_agente_con_cifras_se_omite(alm):
    a = AdvisorGuion([resp_texto("Ok.")])
    list(conversar(alm, [U("hola"), A("El tubo vale $35.000"), U("y el de 8?")], a))
    assert a.llamadas[0]["mensajes"][1]["content"] == MSG_OMITIDO


def test_mensaje_del_agente_con_marcadores_viaja_intacto(alm):
    crudo = "Calle 13: costo {{costo:corrida:13}}, margen {{margen:corrida:13}}"
    a = AdvisorGuion([resp_texto("Ok.")])
    list(conversar(alm, [U("hola"), A(crudo), U("y la cali?")], a))
    assert a.llamadas[0]["mensajes"][1]["content"] == crudo


def test_cifra_inventada_por_el_modelo_se_omite(alm):
    a = AdvisorGuion([resp_texto(
        "Vale como $45.000.\n\nCalle 13: costo {{costo:corrida:1}}")])
    eventos = list(conversar(alm, [U("cuanto vale")], a))
    assert eventos[-1][1]["crudo"] == (
        MSG_CIFRA_OMITIDA + "\n\nCalle 13: costo {{costo:corrida:1}}")


def test_limpiar_no_toca_los_marcadores():
    t = "El costo de la Calle 13 es {{costo:corrida:13}}"
    assert limpiar_cifras_inventadas(t) == t


def test_limpiar_omite_la_linea_y_no_la_lista_entera():
    t = "- Tubo 6 {{precio:insumo:1}}\n- Báscula PESO 60.000 KG {{precio:insumo:2}}"
    assert limpiar_cifras_inventadas(t) == (
        "- Tubo 6 {{precio:insumo:1}}\n" + MSG_CIFRA_OMITIDA)


def test_limpiar_respeta_los_nombres_del_catalogo():
    nombre = "BASCULA PESO 60.000 KG"
    t = "- Bascula peso 60.000 kg: {{precio:insumo:3}}"
    assert limpiar_cifras_inventadas(t, {nombre}) == t
    assert limpiar_cifras_inventadas(t) == MSG_CIFRA_OMITIDA   # sin el nombre, se omite


def test_un_nombre_buscado_no_se_omite_en_la_respuesta(alm):
    a = AdvisorGuion([resp_herramienta(("buscar_insumos", "bascula")),
                      resp_texto("- BASCULA PESO 60.000 KG: {{precio:insumo:3}}")])
    eventos = list(conversar(alm, [U("cuanto vale la bascula")], a))
    assert eventos[-1][1]["crudo"] == "- BASCULA PESO 60.000 KG: {{precio:insumo:3}}"


def test_el_id_de_un_marcador_no_es_un_hueco_del_detector(alm):
    """Un cliente que arma el historial no puede esconder montos dentro de un marcador."""
    a = AdvisorGuion([resp_texto("Ok.")])
    eventos = list(conversar(alm, [U("hola {{x:y:el tubo vale $45.000 pesos}}")], a))
    assert eventos[0][0] == "bloqueado" and a.llamadas == []

    a = AdvisorGuion([resp_texto("Ok.")])
    list(conversar(alm, [U("hola"), A("ok {{costo:apu:cuesta $35.000 COP|DIURNO}}"),
                         U("y?")], a))
    assert a.llamadas[0]["mensajes"][1]["content"] == MSG_OMITIDO


def test_historial_legitimo_con_codigos_viaja_intacto(alm):
    crudo = "- {{costo:apu:4859 N|NOCTURNO}}\n- {{margen:capitulo:13:2}}"
    a = AdvisorGuion([resp_texto("Ok.")])
    list(conversar(alm, [U("hola"), A(crudo), U("y?")], a))
    assert a.llamadas[0]["mensajes"][1]["content"] == crudo


def test_un_porcentaje_resuelto_en_el_historial_se_omite(alm):
    a = AdvisorGuion([resp_texto("Ok.")])
    list(conversar(alm, [U("hola"), A("Total 850 y margen 12,3 %"), U("y?")], a))
    assert a.llamadas[0]["mensajes"][1]["content"] == MSG_OMITIDO


def test_el_tope_apaga_las_herramientas(alm):
    cinco = resp_herramienta(*[("buscar_insumos", "tubo")] * 5)
    a = AdvisorGuion([cinco, resp_texto("Listo.")])
    list(conversar(alm, [U("busca")], a))
    resultados = a.llamadas[1]["mensajes"][-1]["content"]
    assert resultados[4]["is_error"] is True
    assert a.llamadas[1]["con_herramientas"] is False


def test_respuesta_vacia_es_error(alm):
    a = AdvisorGuion([resp_texto("   ")])
    assert list(conversar(alm, [U("hola")], a))[-1][0] == "error"


def test_sin_mensaje_del_usuario_es_error(alm):
    assert list(conversar(alm, [A("hola")], AdvisorGuion([])))[0][0] == "error"


def test_privacy_violation_no_se_traga(alm, monkeypatch):
    monkeypatch.setattr(consulta_chat.HerramientasConsulta, "ejecutar",
                        lambda self, n, e: {"precio": 1})
    a = AdvisorGuion([resp_herramienta(("buscar_insumos", "tubo"))])
    with pytest.raises(privacy.PrivacyViolation):
        list(conversar(alm, [U("busca")], a))
```

- [ ] **Step 2: Confirma que fallan**

Run: `python -m pytest tests/test_consulta_chat_motor.py -q`
Expected: FAIL con `ImportError: cannot import name 'MSG_CIFRA_OMITIDA'`

- [ ] **Step 3: Implementa**

Reemplaza el bloque de import de `composicion_chat` en `apu_tool/dominio/consulta_chat.py` por este, que junta los dos, y agrega el de `ai_assist`. `ApuAdvisor` se **reexporta** desde aquí porque `servicio/` no puede nombrar `ai_assist` (`tests/test_servicio_privacidad.py::test_servicio_no_importa_ai_assist`); es el mismo patrón de `dominio/composicion_agente.py`:

```python
from apu_tool.dominio.ai_assist import (  # noqa: F401  (re-export: servicio/ no importa la fachada de la IA)
    PROMPT_VERSION_CONSULTA, ApuAdvisor, IANoDisponible,
)
from apu_tool.dominio.composicion_chat import (
    _MAX_VUELTAS, MAX_HERRAMIENTAS, MAX_RESULTADOS_APUS, MAX_RESULTADOS_INSUMOS,
    MIN_RESULTADOS_SIN_SUGERENCIA, MSG_OMITIDO, MSG_REINTENTAR, SUGERENCIA_POCOS,
    _acotar,
)
```

Agrega al final del archivo:

```python
# ----------------------------------------------------------------- marcadores
# `{{<campo>:<tipo>:<id>}}`. El id de un capítulo lleva ":" adentro (`12:2`) y el de
# un APU lleva "|" (`4859|DIURNO`): por eso el id es "todo hasta las llaves".
MARCADOR = re.compile(r"\{\{\s*([a-z_]+)\s*:\s*([a-z]+)\s*:\s*([^{}]*?)\s*\}\}",
                      re.IGNORECASE)
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
    patrones = [re.compile(re.escape(n), re.IGNORECASE)
                for n in sorted({n for n in conocidos if n}, key=len, reverse=True)]

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
    return str(entrada.get("texto", ""))[:200]


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
            motivo = privacy.texto_con_dinero(sin_marcadores(m["texto"]))
            if motivo:
                yield ("bloqueado", {"motivo": motivo})
                return
        else:
            visible = sin_marcadores(m["texto"])
            if privacy.cifra_monetaria(visible) or _PORCENTAJE.search(visible):
                m["texto"] = MSG_OMITIDO

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
```

- [ ] **Step 4: Confirma que pasan**

Run: `python -m pytest tests/test_consulta_chat_motor.py tests/test_consulta_chat_herramientas.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/consulta_chat.py tests/test_consulta_chat_motor.py
git commit -m "feat(consulta): marcadores, candado de cifras inventadas y bucle de tool use"
```

---

### Task 7: El reemplazo de marcadores (`servicio/consulta.py`)

**Files:**
- Create: `apu_tool/servicio/consulta.py`
- Test: `tests/test_consulta_resolver.py`

- [ ] **Step 1: Escribe las pruebas que fallan**

```python
"""El reemplazo de marcadores: el único punto del chat de consulta que toca dinero.
Las cifras se comparan contra las MISMAS funciones de la pantalla."""
import pytest

from apu_tool.dominio.pricing import PricingEngine
from apu_tool.servicio import consulta
from apu_tool.servicio.consulta import NO_DISPONIBLE, SIN_PRECIO, pct, pesos, resolver
from apu_tool.servicio.corridas import vista_corrida
from tests.consulta_base import almacen_consulta


@pytest.fixture()
def base(tmp_path):
    return almacen_consulta(tmp_path)


def test_formatos():
    assert pesos(1234567) == "$1.234.567"
    assert pesos(-1500.5) == "$-1.501"
    assert pct(0.1234) == "12.3%"                  # igual que la web


def test_marcador_con_mayusculas_igual_se_resuelve(base):
    alm, _ = base
    assert resolver(alm, "{{Costo:APU:A1|DIURNO}}") == "$22.000"


def test_tope_de_corridas_por_respuesta(base, monkeypatch):
    alm, ids = base
    monkeypatch.setattr(consulta, "MAX_CORRIDAS_POR_RESPUESTA", 1)
    texto = resolver(alm, f"{{{{costo:corrida:{ids['cali']}}}}} "
                          f"{{{{costo:corrida:{ids['calle13']}}}}}")
    assert texto.endswith(NO_DISPONIBLE) and not texto.startswith(NO_DISPONIBLE)


def test_precio_de_insumo(base):
    alm, ids = base
    assert resolver(alm, f"{{{{precio:insumo:{ids['insumo_tubo']}}}}}") == "$35.000"


def test_insumo_en_cero_dice_sin_precio_nunca_cero(base):
    alm, ids = base
    assert resolver(alm, f"{{{{precio:insumo:{ids['insumo_cero']}}}}}") == SIN_PRECIO


def test_costo_de_apu_es_el_del_motor(base):
    alm, _ = base
    _, total = PricingEngine(alm).cost_apu("A1", "DIURNO")
    assert resolver(alm, "{{costo:apu:A1|DIURNO}}") == pesos(total) == "$22.000"
    assert resolver(alm, "{{costo:apu:A1 N|NOCTURNO}}") == "$24.000"


def test_apu_con_componente_con_alerta_dice_revisar(base):
    alm, _ = base
    assert "revisar" in resolver(alm, "{{costo:apu:A3|DIURNO}}")


def test_totales_de_corrida_son_los_de_la_vista(base):
    alm, ids = base
    cid = ids["cali"]
    t = vista_corrida(alm, cid)["totales"]
    assert resolver(alm, f"{{{{contractual:corrida:{cid}}}}}") == pesos(t["contractual"])
    assert resolver(alm, f"{{{{costo:corrida:{cid}}}}}") == pesos(t["costo"])
    assert resolver(alm, f"{{{{diferencia:corrida:{cid}}}}}") == pesos(t["margen"])
    assert resolver(alm, f"{{{{margen:corrida:{cid}}}}}") == pct(t["margen_pct"])


def test_corrida_con_filas_sin_costear_es_parcial_menos_el_contractual(base):
    alm, ids = base
    cid = ids["calle13"]
    assert "parcial: 2 de 3 actividades costeadas" in resolver(
        alm, f"{{{{costo:corrida:{cid}}}}}")
    assert "parcial" not in resolver(alm, f"{{{{contractual:corrida:{cid}}}}}")


def test_capitulos(base):
    alm, ids = base
    cid = ids["calle13"]
    caps = {c["codigo"]: c for c in vista_corrida(alm, cid)["capitulos"]}
    assert resolver(alm, f"{{{{costo:capitulo:{cid}:1}}}}") == pesos(caps["1"]["costo"])
    assert resolver(alm, f"{{{{diferencia:capitulo:{cid}:2}}}}").startswith(
        pesos(caps["2"]["diferencia"]))
    assert "parcial: 1 de 2 actividades costeadas" in resolver(
        alm, f"{{{{costo:capitulo:{cid}:2}}}}")
    assert resolver(alm, f"{{{{contractual:capitulo:{cid}:2}}}}") == pesos(
        caps["2"]["contractual"])


@pytest.mark.parametrize("marcador", [
    "{{precio:corrida:1}}",          # campo que no va con ese tipo
    "{{costo:obra:1}}",              # tipo desconocido
    "{{precio:insumo:999999}}",      # id inexistente
    "{{precio:insumo:abc}}",         # id ilegible
    "{{costo:apu:NOEXISTE|DIURNO}}",
    "{{costo:corrida:999}}",
    "{{costo:capitulo:1:77}}",       # capítulo que la corrida no tiene
])
def test_marcador_invalido_no_adivina(base, marcador):
    alm, _ = base
    assert resolver(alm, marcador) == NO_DISPONIBLE


def test_corrida_a_medio_armar_es_parcial_en_todo(base, monkeypatch):
    alm, ids = base
    real = consulta.vista_corrida

    def armando(a, cid):
        v = real(a, cid)
        v["armado"] = {"hechos": 290, "total": 1939}
        return v
    monkeypatch.setattr(consulta, "vista_corrida", armando)
    for campo in ("contractual", "costo"):
        assert "parcial: armado 290 de 1939 actividades" in resolver(
            alm, f"{{{{{campo}:corrida:{ids['cali']}}}}}")


def test_una_vista_por_corrida_y_por_respuesta(base, monkeypatch):
    alm, ids = base
    llamadas = []
    real = consulta.vista_corrida
    monkeypatch.setattr(consulta, "vista_corrida",
                        lambda a, cid: llamadas.append(cid) or real(a, cid))
    cid = ids["calle13"]
    resolver(alm, f"{{{{costo:corrida:{cid}}}}} {{{{contractual:corrida:{cid}}}}} "
                  f"{{{{costo:capitulo:{cid}:1}}}}")
    assert llamadas == [cid]


def test_una_excepcion_no_tumba_la_respuesta(base, monkeypatch):
    alm, ids = base

    def revienta(a, cid):
        raise RuntimeError("boom")
    monkeypatch.setattr(consulta, "vista_corrida", revienta)
    texto = resolver(alm, f"Total: {{{{costo:corrida:{ids['cali']}}}}}.")
    assert texto == f"Total: {NO_DISPONIBLE}."


def test_el_texto_alrededor_no_se_toca(base):
    alm, _ = base
    assert resolver(alm, "Hola, sin cifras.") == "Hola, sin cifras."
```

- [ ] **Step 2: Confirma que fallan**

Run: `python -m pytest tests/test_consulta_resolver.py -q`
Expected: FAIL con `ImportError: cannot import name 'consulta' from 'apu_tool.servicio'`

- [ ] **Step 3: Implementa**

`apu_tool/servicio/consulta.py`:

```python
"""Chat de consulta, el lado CON dinero: reemplaza los marcadores que escribió la IA
por las cifras reales. Nada de lo que pasa acá vuelve al modelo.

Las cifras salen de las MISMAS funciones de la pantalla (`vista_corrida`, que usa
`resumen_por_capitulo`, y `PricingEngine`): es la única forma de que el chat diga el
mismo número que la corrida. Sumar acá sería la tercera suma que `resumen_por_capitulo`
existe para evitar. Spec: docs/superpowers/specs/2026-11-25-chat-consulta-design.md
"""
from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.dominio import consulta_chat
# OJO: ni en un comentario puede aparecer aquí el nombre del módulo de la fachada de
# la IA: `test_servicio_no_importa_<…>` busca la subcadena en todo `servicio/`.
from apu_tool.dominio.consulta_chat import ApuAdvisor, IANoDisponible
from apu_tool.dominio.alertas import CALIDADES_CON_ALERTA
from apu_tool.dominio.pricing import PricingEngine
from apu_tool.servicio.corridas import vista_corrida

logger = logging.getLogger(__name__)

NO_DISPONIBLE = "[cifra no disponible]"
SIN_PRECIO = "sin precio en la lista Principal"
MAX_CORRIDAS_POR_RESPUESTA = 5
# Marcador → clave en la vista. Ojo: en `totales` la diferencia en pesos se llama
# `margen` y el porcentaje `margen_pct`; en los capítulos, `diferencia` y `margen_pct`.
_CAMPOS_CORRIDA = {"contractual": "contractual", "costo": "costo",
                   "diferencia": "margen", "margen": "margen_pct"}
_CAMPOS_CAPITULO = {"contractual": "contractual", "costo": "costo",
                    "diferencia": "diferencia", "margen": "margen_pct"}


def pesos(v: float) -> str:
    """Como `web/src/lib/moneda.ts`, redondeando medio hacia arriba (regla del repo)."""
    n = int(Decimal(str(v)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return "$" + f"{n:,}".replace(",", ".")


def pct(v: float) -> str:
    """Como `pct` de `web/src/lib/moneda.ts` («12.3%»): el chat dice lo que dice la pantalla."""
    return f"{(v or 0) * 100:.1f}%"


def _fmt(campo: str, v: float) -> str:
    return pct(v) if campo == "margen" else pesos(v)


def _costeada(it: dict) -> bool:
    """La regla de `report_categorizado._costeada`, sobre la fila de la vista."""
    return bool(it.get("apu_codigo")) or (it.get("costo_unitario") or 0) > 0


class _Resolutor:
    """Una instancia por respuesta: memo de `vista_corrida` (varios marcadores de la
    misma corrida comparten la vista) y un `PricingEngine` compartido."""

    def __init__(self, alm: Almacen):
        self.alm = alm
        self._vistas: dict[int, dict | None] = {}
        self._pricing: PricingEngine | None = None

    def vista(self, cid: int):
        if cid not in self._vistas:
            # Cada corrida distinta es un `vista_corrida` completo (y egress de
            # Supabase): más de MAX_CORRIDAS_POR_RESPUESTA salen «no disponible».
            if len(self._vistas) >= MAX_CORRIDAS_POR_RESPUESTA:
                return None
            self._vistas[cid] = vista_corrida(self.alm, cid)
        return self._vistas[cid]

    def cifra(self, campo: str, tipo: str, ident: str) -> str:
        if tipo == "insumo" and campo == "precio":
            return self._insumo(ident)
        if tipo == "apu" and campo == "costo":
            return self._apu(ident)
        if tipo == "corrida" and campo in _CAMPOS_CORRIDA:
            return self._corrida(campo, ident)
        if tipo == "capitulo" and campo in _CAMPOS_CAPITULO:
            return self._capitulo(campo, ident)
        return NO_DISPONIBLE

    def _insumo(self, ident: str) -> str:
        ins = self.alm.precios.get_insumo_por_id(int(ident))   # lista Principal
        if ins is None:
            return NO_DISPONIBLE
        if ins.sin_precio or not ins.precio > 0:     # regla "nada en $0"
            return SIN_PRECIO
        return pesos(ins.precio)

    def _apu(self, ident: str) -> str:
        codigo, _, turno = ident.rpartition("|")
        if not codigo:
            return NO_DISPONIBLE
        if self._pricing is None:
            self._pricing = PricingEngine(self.alm)            # lista Principal
        costeados, total = self._pricing.cost_apu(codigo, turno.upper())
        if not costeados:
            return NO_DISPONIBLE
        malos = sum(1 for c in costeados
                    if c.costo <= 0 or c.calidad_cruce in CALIDADES_CON_ALERTA)
        if total <= 0:
            return "sin costo: sus componentes no tienen precio"
        nota = (f" (revisar: {malos} de {len(costeados)} componentes con alerta de "
                "costeo)") if malos else ""
        return pesos(total) + nota

    @staticmethod
    def _nota_armado(v: dict) -> str:
        a = v.get("armado")
        return (f" (parcial: armado {a['hechos']} de {a['total']} actividades)"
                if a else "")

    def _corrida(self, campo: str, ident: str) -> str:
        v = self.vista(int(ident))
        if v is None:
            return NO_DISPONIBLE
        s = _fmt(campo, v["totales"][_CAMPOS_CORRIDA[campo]])
        nota = self._nota_armado(v)
        if not nota and campo != "contractual":
            items = v["items"]
            hechas = sum(1 for it in items if _costeada(it))
            if hechas < len(items):
                nota = f" (parcial: {hechas} de {len(items)} actividades costeadas)"
            elif v["totales"].get("n_alertas_costeo"):
                # Mismo criterio que el capítulo: filas con APU pero con algún
                # componente en $0 o con cruce dudoso.
                nota = " (con alertas de costeo)"
        return s + nota

    def _capitulo(self, campo: str, ident: str) -> str:
        cid, _, cod = ident.partition(":")
        v = self.vista(int(cid))
        if v is None:
            return NO_DISPONIBLE
        cap = next((c for c in v["capitulos"] if c["codigo"] == cod), None)
        if cap is None:
            return NO_DISPONIBLE
        s = _fmt(campo, cap[_CAMPOS_CAPITULO[campo]])
        nota = self._nota_armado(v)
        if not nota and campo != "contractual":
            if cap["sin_apu"]:
                nota = (f" (parcial: {cap['con_apu']} de {cap['actividades']} "
                        "actividades costeadas)")
            elif not cap["completo"]:
                nota = " (con alertas de costeo)"
        return s + nota


def resolver(alm: Almacen, texto: str) -> str:
    """`texto` con cada marcador reemplazado por su cifra. Un marcador que no se puede
    resolver sale como NO_DISPONIBLE: nunca se adivina ni se acerca a otro."""
    r = _Resolutor(alm)

    def uno(m) -> str:
        try:
            return r.cifra(m.group(1).lower(), m.group(2).lower(), m.group(3).strip())
        except (ValueError, TypeError, KeyError):
            return NO_DISPONIBLE                       # id ilegible: no es un error
        except Exception:
            logger.exception("No se pudo resolver el marcador %s", m.group(0))
            return NO_DISPONIBLE

    return consulta_chat.MARCADOR.sub(uno, texto or "")


def _con_cifras(alm: Almacen, eventos):
    for evento, payload in eventos:
        if evento == "respuesta":
            payload = dict(payload, texto=resolver(alm, payload["crudo"]))
        yield evento, payload


def chat_stream(alm: Almacen, datos: dict):
    """El generador SSE del chat de consulta. Lanza IANoDisponible (503) ANTES de
    abrir el stream. No persiste nada."""
    if not config.ai_available():
        raise IANoDisponible(
            "Consultar al agente necesita ANTHROPIC_API_KEY en el servidor.")
    return _con_cifras(alm, consulta_chat.conversar(
        alm, datos.get("mensajes") or [], ApuAdvisor()))
```

- [ ] **Step 4: Confirma que pasan**

Run: `python -m pytest tests/test_consulta_resolver.py -q`
Expected: PASS. Si `test_apu_con_componente_con_alerta_dice_revisar` falla, imprime `PricingEngine(alm).cost_apu("A3", "DIURNO")` para ver la `calidad_cruce` real de un código que no está en el catálogo y ajusta la **prueba** (el código `9999`), no `CALIDADES_CON_ALERTA`.

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/consulta.py tests/test_consulta_resolver.py
git commit -m "feat(consulta): reemplazo de marcadores con las cifras de vista_corrida y PricingEngine"
```

---

### Task 8: El endpoint `POST /api/consulta/chat`

**Files:**
- Modify: `apu_tool/servicio/esquemas.py` (después de `ChatComposicionIn`)
- Modify: `apu_tool/servicio/rutas.py` (import de esquemas línea ~48, import de servicios, y el endpoint después de `chat_composicion`)
- Test: `tests/test_api_consulta_chat.py`

- [ ] **Step 1: Escribe las pruebas que fallan**

```python
"""El endpoint del chat de consulta."""
import pytest

from apu_tool.servicio import consulta as consulta_svc
from tests.chat_falso import AdvisorGuion, resp_texto
from tests.conftest import cliente
from tests.consulta_base import almacen_consulta

URL = "/api/consulta/chat"


@pytest.fixture()
def app_ids(tmp_path):
    from apu_tool.servicio.app import create_app
    alm, ids = almacen_consulta(tmp_path)
    return create_app(almacen=alm), ids


def _con_guion(monkeypatch, respuestas):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    a = AdvisorGuion(respuestas)
    monkeypatch.setattr(consulta_svc, "ApuAdvisor", lambda: a)
    return a


def test_rol_consulta_recibe_las_cifras_resueltas(app_ids, monkeypatch):
    app, ids = app_ids
    _con_guion(monkeypatch, [resp_texto(
        f"El tubo vale {{{{precio:insumo:{ids['insumo_tubo']}}}}}.")])
    r = cliente(app, "consulta").post(URL, json={
        "mensajes": [{"rol": "usuario", "texto": "cuanto vale la tuberia de 6"}]})
    assert r.status_code == 200
    assert "event: respuesta" in r.text
    assert "$35.000" in r.text                          # texto con la cifra
    assert "{{precio:insumo:" in r.text                 # y el crudo para el historial


def test_mensaje_con_dinero_bloquea(app_ids, monkeypatch):
    app, _ = app_ids
    a = _con_guion(monkeypatch, [])
    r = cliente(app, "consulta").post(URL, json={
        "mensajes": [{"rol": "usuario", "texto": "mas de $50.000"}]})
    assert "event: bloqueado" in r.text and a.llamadas == []


def test_sin_credencial_es_503(app_ids, monkeypatch):
    app, _ = app_ids
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = cliente(app, "consulta").post(URL, json={
        "mensajes": [{"rol": "usuario", "texto": "hola"}]})
    assert r.status_code == 503


def test_cuerpo_absurdo_es_422(app_ids, monkeypatch):
    app, _ = app_ids
    _con_guion(monkeypatch, [])
    r = cliente(app, "consulta").post(URL, json={
        "mensajes": [{"rol": "usuario", "texto": "x"}] * 101})
    assert r.status_code == 422
```

- [ ] **Step 2: Confirma que fallan**

Run: `python -m pytest tests/test_api_consulta_chat.py -q`
Expected: FAIL con status 404 en lugar de 200/503.

- [ ] **Step 3: Implementa el esquema**

En `apu_tool/servicio/esquemas.py`, después de `class ChatComposicionIn`:

```python
class ChatConsultaIn(BaseModel):
    """El historial del chat de consulta (lo guarda el navegador). Los mensajes del
    agente llegan con MARCADORES, no con cifras; el servidor igual los revisa."""
    mensajes: list[MensajeChatIn] = Field(max_length=100)
```

- [ ] **Step 4: Implementa el endpoint**

En `apu_tool/servicio/rutas.py`:

1. Agrega `ChatConsultaIn` a la lista importada de `apu_tool.servicio.esquemas` (la que ya trae `ChatComposicionIn`, línea ~48).
2. Junto a los otros imports de servicios, agrega: `from apu_tool.servicio import consulta as consulta_svc`
3. Después de la función `chat_composicion`:

```python
@router.post("/consulta/chat")
def chat_consulta(body: ChatConsultaIn, alm: Almacen = Depends(get_almacen),
                  actor=Depends(requiere_rol("consulta"))):
    """Preguntas de precios y totales. La IA no ve cifras: escribe marcadores y el
    servidor los reemplaza (servicio/consulta.py). No persiste nada."""
    try:
        gen = consulta_svc.chat_stream(alm, body.model_dump())
    except svc.IANoDisponible as e:
        raise HTTPException(status_code=503, detail=str(e))
    return StreamingResponse(_event_stream(gen),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})
```

`svc.IANoDisponible` es la misma clase que lanza `consulta.chat_stream`: `dominio/revision.py` la reexporta desde `ai_assist`.

- [ ] **Step 5: Confirma que pasan, con toda la suite**

Run: `python -m pytest tests/test_api_consulta_chat.py -q && python -m pytest tests/ -q`
Expected: PASS en las dos. Si algún test cuenta endpoints (busca `73` en `tests/`), súbelo a 74.

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/esquemas.py apu_tool/servicio/rutas.py tests/test_api_consulta_chat.py
git commit -m "feat(consulta): POST /api/consulta/chat (SSE, rol consulta)"
```

---

### Task 9: Cliente web y tipos

**Files:**
- Modify: `web/src/lib/tipos.ts` (después de `MensajeChat`, línea ~211)
- Create: `web/src/api/consulta.ts`

- [ ] **Step 1: Agrega el tipo**

En `web/src/lib/tipos.ts`, después de `interface MensajeChat`:

```ts
/** Respuesta del chat de consulta. `crudo` lleva MARCADORES ({{costo:corrida:12}}) y
 *  es lo ÚNICO que vuelve como historial: la IA nunca ve cifras. `texto` trae las
 *  cifras que puso el servidor y solo se muestra. */
export interface RespuestaConsulta {
  texto: string;
  crudo: string;
  modelo: string;
  prompt_version: string;
}
```

- [ ] **Step 2: Crea el cliente**

`web/src/api/consulta.ts`:

```ts
import { consumirSse } from "@/api/corridas";
import type { MensajeChat } from "@/lib/tipos";

/** Chat de consulta (SSE). Eventos: `pensando`, `buscando` {herramienta, consulta},
 *  `respuesta` (RespuestaConsulta), `bloqueado` {motivo}, `error` {detail}.
 *  No persiste nada. */
export function chatConsultaStream(
  mensajes: MensajeChat[],
  onEvent: (e: { event: string; data: unknown }) => void,
  signal?: AbortSignal,
): Promise<void> {
  return consumirSse(
    "/consulta/chat",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mensajes }),
      signal,
    },
    onEvent,
  );
}
```

- [ ] **Step 3: Compila**

Run: `cd web && npm run build`
Expected: build OK, sin errores de tipos.

- [ ] **Step 4: Commit**

```bash
git add web/src/lib/tipos.ts web/src/api/consulta.ts
git commit -m "feat(web): cliente SSE del chat de consulta"
```

---

### Task 10: El panel `ChatConsulta`

**Files:**
- Create: `web/src/components/consulta/ChatConsulta.tsx`
- Test: `web/src/components/consulta/ChatConsulta.test.tsx`

- [ ] **Step 1: Escribe las pruebas que fallan**

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import ChatConsulta from "./ChatConsulta";

const chatConsultaStream = vi.fn();
vi.mock("@/api/consulta", () => ({
  chatConsultaStream: (...a: unknown[]) => chatConsultaStream(...a),
}));

type OnEv = (e: { event: string; data: unknown }) => void;

function responder(texto: string, crudo: string) {
  chatConsultaStream.mockImplementationOnce(async (_m: unknown, onEv: OnEv) => {
    onEv({ event: "respuesta",
           data: { texto, crudo, modelo: "m", prompt_version: "consulta/v1" } });
  });
}

function escribirYEnviar(texto: string) {
  fireEvent.change(screen.getByRole("textbox"), { target: { value: texto } });
  fireEvent.click(screen.getByRole("button", { name: /enviar/i }));
}

beforeEach(() => {
  chatConsultaStream.mockReset();
  sessionStorage.clear();
});

test("muestra las cifras pero manda el crudo como historial", async () => {
  responder("El tubo vale $35.000.", "El tubo vale {{precio:insumo:7}}.");
  render(<ChatConsulta iaDisponible />);
  fireEvent.click(screen.getByRole("button", { name: /abrir el agente de consulta/i }));
  escribirYEnviar("cuanto vale el tubo");
  expect(await screen.findByText("El tubo vale $35.000.")).toBeTruthy();

  responder("Ok.", "Ok.");
  escribirYEnviar("y el de 8?");
  await waitFor(() => expect(chatConsultaStream).toHaveBeenCalledTimes(2));
  const historial = chatConsultaStream.mock.calls[1][0] as { rol: string; texto: string }[];
  expect(historial[1]).toEqual({ rol: "agente", texto: "El tubo vale {{precio:insumo:7}}." });
  expect(JSON.stringify(historial)).not.toContain("35.000");
});

test("sin IA el botón queda deshabilitado", () => {
  render(<ChatConsulta iaDisponible={false} />);
  const boton = screen.getByRole("button", { name: /abrir el agente de consulta/i });
  expect((boton as HTMLButtonElement).disabled).toBe(true);
});

test("el hilo sobrevive a recargar (sessionStorage)", () => {
  sessionStorage.setItem("chat-consulta", JSON.stringify({
    abierto: true,
    hilo: [{ id: 1, rol: "usuario", texto: "hola" },
           { id: 2, rol: "agente", texto: "Total $10", crudo: "Total {{costo:corrida:1}}" }],
  }));
  render(<ChatConsulta iaDisponible />);
  expect(screen.getByText("Total $10")).toBeTruthy();
});

test("bloqueado devuelve el mensaje a la caja y avisa", async () => {
  chatConsultaStream.mockImplementationOnce(async (_m: unknown, onEv: OnEv) => {
    onEv({ event: "bloqueado", data: { motivo: "El mensaje parece traer un monto" } });
  });
  render(<ChatConsulta iaDisponible />);
  fireEvent.click(screen.getByRole("button", { name: /abrir el agente de consulta/i }));
  escribirYEnviar("mas de $50.000");
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("mas de $50.000");
});
```

- [ ] **Step 2: Confirma que fallan**

Run: `cd web && npx vitest run src/components/consulta/ChatConsulta.test.tsx`
Expected: FAIL, porque `./ChatConsulta` no existe.

- [ ] **Step 3: Implementa**

`web/src/components/consulta/ChatConsulta.tsx`:

```tsx
import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { chatConsultaStream } from "@/api/consulta";
import AvatarIngeniero, { type EstadoAvatar } from "@/components/composicion/AvatarIngeniero";
import type { MensajeChat, RespuestaConsulta } from "@/lib/tipos";

interface Entrada {
  id: number;
  rol: "usuario" | "agente";
  /** Lo que se muestra (con cifras, si es del agente). */
  texto: string;
  /** Solo del agente: el texto con MARCADORES. Es lo único que vuelve al servidor. */
  crudo?: string;
}

const CLAVE = "chat-consulta";
const MAX_HISTORIAL = 20;
const MAX_TEXTO = 1000;

function leerGuardado(): { hilo: Entrada[]; abierto: boolean } {
  try {
    const v = JSON.parse(sessionStorage.getItem(CLAVE) ?? "null");
    if (v && Array.isArray(v.hilo)) return { hilo: v.hilo, abierto: !!v.abierto };
  } catch {
    /* storage bloqueado o JSON roto: se arranca vacío */
  }
  return { hilo: [], abierto: false };
}

/** El historial NUNCA lleva las cifras: del agente viaja el `crudo`. Si no lo hay,
 *  viaja vacío y el servidor lo descarta. */
function paraHistorial(e: Entrada): MensajeChat {
  return { rol: e.rol, texto: e.rol === "agente" ? (e.crudo ?? "") : e.texto };
}

/** Chat de consulta: precios de insumos, costos de APUs y totales de corridas o
 *  capítulos. Vive en el Layout, así que sigue abierto al cambiar de página. */
export default function ChatConsulta({ iaDisponible }: { iaDisponible: boolean }) {
  const [guardado] = useState(leerGuardado);
  const [hilo, setHilo] = useState<Entrada[]>(guardado.hilo);
  const [abierto, setAbierto] = useState(guardado.abierto);
  const [texto, setTexto] = useState("");
  const [estado, setEstado] = useState<EstadoAvatar>("espera");
  const [linea, setLinea] = useState("");
  const [aviso, setAviso] = useState<string | null>(null);
  const proximoId = useRef(Math.max(0, ...guardado.hilo.map((e) => e.id)) + 1);
  const cancelar = useRef<AbortController | null>(null);
  const fin = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    try {
      sessionStorage.setItem(CLAVE, JSON.stringify({ hilo, abierto }));
    } catch {
      /* sin storage: el hilo vive solo en memoria */
    }
  }, [hilo, abierto]);

  useEffect(() => () => cancelar.current?.abort(), []);
  useEffect(() => fin.current?.scrollIntoView?.({ block: "end" }), [hilo, abierto]);

  const ocupado = estado === "pensando" || estado === "buscando";
  const visible: EstadoAvatar = iaDisponible ? estado : "deshabilitado";

  async function enviar() {
    const t = texto.trim();
    if (!t || ocupado || !iaDisponible) return;
    const idUsuario = proximoId.current++;
    const conMensaje: Entrada[] = [...hilo, { id: idUsuario, rol: "usuario", texto: t }];
    setHilo(conMensaje);
    setTexto("");
    setAviso(null);
    setEstado("pensando");
    setLinea("Pensando…");
    const control = new AbortController();
    cancelar.current = control;
    const res: { r: RespuestaConsulta | null; fallo: string | null; bloqueado: boolean } =
      { r: null, fallo: null, bloqueado: false };
    try {
      await chatConsultaStream(
        conMensaje.slice(-MAX_HISTORIAL).map(paraHistorial),
        (ev) => {
          const d = (ev.data ?? {}) as { consulta?: string; motivo?: string; detail?: string };
          if (ev.event === "pensando") {
            setEstado("pensando");
            setLinea("Pensando…");
          } else if (ev.event === "buscando") {
            setEstado("buscando");
            setLinea(`Buscando «${d.consulta ?? ""}»…`);
          } else if (ev.event === "respuesta") {
            res.r = ev.data as RespuestaConsulta;
          } else if (ev.event === "bloqueado" || ev.event === "error") {
            res.fallo = d.motivo ?? d.detail ?? "No pude responder, vuelve a intentar.";
            res.bloqueado = ev.event === "bloqueado";
          }
        },
        control.signal,
      );
    } catch (e) {
      res.fallo = e instanceof Error ? e.message : "No pude responder, vuelve a intentar.";
    }
    setLinea("");
    const r = res.r;
    if (r) {
      setHilo((h) => [...h, { id: proximoId.current++, rol: "agente", texto: r.texto, crudo: r.crudo }]);
      setEstado("espera");
    } else {
      // El mensaje vuelve a la caja: no se queda en el hilo algo que el agente no recibió.
      setHilo((h) => h.filter((x) => x.id !== idUsuario));
      setTexto(t);
      setAviso(res.fallo ?? "El agente no respondió. Vuelve a intentar.");
      setLinea(res.bloqueado ? "Mensaje bloqueado: trae un monto" : "No pude responder");
      setEstado("error");
    }
  }

  if (!abierto) {
    return (
      <button
        type="button"
        aria-label="Abrir el agente de consulta"
        title={iaDisponible ? "Pregúntale al agente por precios y totales"
          : "El agente no está disponible: falta ANTHROPIC_API_KEY en el servidor."}
        disabled={!iaDisponible}
        onClick={() => setAbierto(true)}
        className="fixed right-4 bottom-4 z-40 flex items-center gap-2 rounded-full border border-border bg-background py-1 pr-3 pl-1 text-xs text-foreground shadow-md hover:bg-muted disabled:opacity-50"
      >
        <AvatarIngeniero estado={visible} />
        Preguntar
      </button>
    );
  }

  return (
    <aside
      aria-label="Agente de consulta"
      className="fixed right-4 bottom-4 z-40 flex max-h-[75vh] w-[min(400px,calc(100vw-2rem))] flex-col gap-2 rounded border border-border bg-background p-3 shadow-lg"
    >
      <div className="flex items-center gap-2">
        <AvatarIngeniero estado={visible} />
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold text-foreground">Consulta</p>
          <p aria-live="polite" className="truncate text-[11px] text-muted-foreground">
            {iaDisponible ? linea || "Precios, costos y totales" : "No disponible"}
          </p>
        </div>
        {hilo.length > 0 && (
          <button
            type="button"
            disabled={ocupado}
            className="text-[11px] text-muted-foreground underline underline-offset-2 hover:text-foreground disabled:opacity-50"
            onClick={() => { setHilo([]); setAviso(null); }}
          >
            Limpiar
          </button>
        )}
        <button
          type="button"
          aria-label="Cerrar el agente de consulta"
          className="text-muted-foreground hover:text-foreground"
          onClick={() => setAbierto(false)}
        >
          <X className="size-4" />
        </button>
      </div>

      <div role="log" className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto">
        {hilo.length === 0 && (
          <p className="text-xs text-muted-foreground">
            {"Pregúntame por el precio de un insumo, el costo de un APU o los totales de "
              + "una licitación. Por ejemplo: «¿cuánto vale la tubería PVC de 6\"?» o "
              + "«¿cuál es el total de redes húmedas de la Calle 13?». Las cifras las pone "
              + "el sistema: yo no las veo."}
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
          </div>
        ))}
        <div ref={fin} />
      </div>

      {aviso && (
        <p role="alert" className="border-l-2 border-destructive bg-destructive-surface px-2 py-1 text-xs text-destructive">
          {aviso}
        </p>
      )}

      <div className="flex flex-col gap-1">
        <textarea
          aria-label="Pregunta para el agente"
          rows={2}
          maxLength={MAX_TEXTO}
          value={texto}
          disabled={!iaDisponible || ocupado}
          placeholder="Escribe tu pregunta… (Enter envía, Shift+Enter baja de línea)"
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
          <Button size="sm" disabled={!iaDisponible || ocupado || !texto.trim()}
                  onClick={() => void enviar()}>
            {ocupado ? "Esperando…" : "Enviar"}
          </Button>
        </div>
      </div>
    </aside>
  );
}
```

Ojo con la regla de CLAUDE.md: un texto de usuario largo en un atributo JSX va como expresión (`title={...}`), **nunca** partido en dos líneas dentro de comillas.

- [ ] **Step 4: Confirma que pasan**

Run: `cd web && npx vitest run src/components/consulta/ChatConsulta.test.tsx`
Expected: PASS. Si `AvatarIngeniero` dentro del `<button>` hace que el nombre accesible no case con `/abrir el agente de consulta/i`, mantén el `aria-label` del botón: es lo que debe ganar.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/consulta/
git commit -m "feat(web): panel flotante del chat de consulta"
```

---

### Task 11: Montarlo en el Layout

**Files:**
- Modify: `web/src/components/Layout.tsx` (imports y antes del cierre del `div` raíz, línea ~277)
- Modify: `web/src/components/Layout.test.tsx` (mocks)

- [ ] **Step 1: Agrega el mock al test del Layout**

En `web/src/components/Layout.test.tsx`, junto a los otros `vi.mock`:

```tsx
vi.mock("@/api/consulta", () => ({ chatConsultaStream: vi.fn() }));
```

- [ ] **Step 2: Monta el panel**

En `web/src/components/Layout.tsx`, agrega el import:

```tsx
import ChatConsulta from "@/components/consulta/ChatConsulta";
```

Y justo después de `</main>`, antes del `</div>` que cierra el layout:

```tsx
      {/* En el Layout y no en una página: así sigue abierto al navegar. */}
      <ChatConsulta iaDisponible={!!status?.ia} />
```

- [ ] **Step 3: Corre el frontend completo**

Run: `cd web && npx vitest run && npm run build`
Expected: todo PASS y build OK.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/Layout.tsx web/src/components/Layout.test.tsx
git commit -m "feat(web): el chat de consulta vive en el Layout"
```

---

### Task 12: Documentación

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Actualiza CLAUDE.md**

1. **Flujo de arquitectura**, debajo de la línea de la mesa de composición:
   ```
   chat de consulta (siempre a mano) ──► IA busca (sin dinero) y escribe marcadores ──► servidor pone las cifras
   ```
2. Cambia «73 endpoints» por «74 endpoints».
3. **Tabla `dominio/`**, una fila:
   `| consulta_chat.py | chat de consulta: herramientas sin dinero (insumos, APUs, proyectos, capítulos), gramática de marcadores, candado de cifras inventadas y bucle de tool use |`
4. **Tabla `servicio/`**, una fila:
   `| consulta.py | chat de consulta, el lado con dinero: reemplaza los marcadores con las cifras de vista_corrida y PricingEngine |`
5. **Sección Datos**, un párrafo nuevo después de «Chat con el agente (2026-11)»:

   ```markdown
   **Chat de consulta (2026-11).** Un botón flotante en el Layout abre un chat que
   responde precios de insumos, costos de APUs y totales de corridas o capítulos
   (`POST /api/consulta/chat`, rol `consulta`, SSE, no persiste). La IA **no ve
   cifras**: sus herramientas devuelven nombres y `ref`, y ella escribe marcadores
   `{{campo:tipo:id}}` (`precio:insumo:<id>`, `costo:apu:<cod>|<TURNO>`,
   `contractual|costo|diferencia|margen` sobre `corrida:<id>` o
   `capitulo:<corrida>:<cod>`). `servicio/consulta.py::resolver` los reemplaza
   DESPUÉS de la última vuelta, con `vista_corrida` y `PricingEngine`, para decir el
   mismo número que la pantalla. Todo es lista Principal. Un marcador que no resuelve
   sale «[cifra no disponible]», una cifra con filas sin costear o con el armado a
   medias sale «(parcial: …)», y un insumo en $0 sale «sin precio». La respuesta trae
   `texto` (con cifras, solo se muestra) y `crudo` (con marcadores, es lo único que
   vuelve como historial). El texto del agente se revisa con `privacy.cifra_monetaria`
   (señales fuertes) y no con `texto_con_dinero`, que daría falsos positivos con
   «el costo de la Calle 13». Las corridas de un proyecto no se suman. Spec:
   `docs/superpowers/specs/2026-11-25-chat-consulta-design.md`.
   ```
6. **No hacer**, tres viñetas:

   ```markdown
   - No le devuelvas al modelo una cifra resuelta. El reemplazo de marcadores va
     DESPUÉS de la última vuelta (`servicio/consulta.py::_con_cifras`), y el
     historial viaja con el `crudo`. Si un cliente manda el texto con cifras, el
     servidor lo omite (`cifra_monetaria`), pero no dependas de eso.
   - No sumes en el chat de consulta. Las cifras salen de `vista_corrida` y
     `PricingEngine`, y las corridas de un proyecto no se suman (suelen ser versiones
     de la misma licitación).
   - No cambies `cifra_monetaria` por `texto_con_dinero` en el texto del agente de
     consulta: omitiría casi toda respuesta que nombre un proyecto con número.
   ```

- [ ] **Step 2: Corre la suite completa**

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: chat de consulta en CLAUDE.md"
```

---

### Task 13: Smoke real y navegador (manual, antes del merge)

**Files:**
- Create: `scripts/smoke_chat_consulta.py`

- [ ] **Step 1: Escribe el smoke**

```python
"""Smoke real del chat de consulta: las preguntas del spec contra la base y la API
reales. Solo LEE (el chat no persiste nada).

Uso:  ANTHROPIC_API_KEY=... python scripts/smoke_chat_consulta.py ["pregunta" ...]
Ojo: con DATABASE_URL en el entorno, `Almacen()` lee la base de PRODUCCIÓN. Es lo que
se quiere para tener "La Cali" y "Calle 13", y es seguro porque no se escribe nada.
"""
import sys
from pathlib import Path

# `python scripts/x.py` pone scripts/ en sys.path, no la raíz (igual que
# scripts/smoke_chat_composicion.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apu_tool.datos.almacen import Almacen  # noqa: E402
from apu_tool.servicio import consulta  # noqa: E402

PREGUNTAS = [
    "¿Cuánto cuesta la actividad de mezcla asfáltica?",
    "¿Cuánto vale el insumo de tubería?",
    "¿Cuál es el total contractual y costo de la licitación del proyecto La Cali?",
    "¿Cuál es el total de redes húmedas de la Calle 13?",
]


def main(preguntas):
    alm = Almacen()
    for p in preguntas:
        print("=" * 72, f"\n> {p}")
        for evento, data in consulta.chat_stream(
                alm, {"mensajes": [{"rol": "usuario", "texto": p}]}):
            if evento == "buscando":
                print(f"  · {data['herramienta']}({data['consulta']})")
            elif evento == "respuesta":
                print("--- crudo (lo que escribió la IA):\n" + data["crudo"])
                print("--- texto (lo que ve la persona):\n" + data["texto"])
            elif evento in ("bloqueado", "error"):
                print(f"  {evento}: {data}")


if __name__ == "__main__":
    main(sys.argv[1:] or PREGUNTAS)
```

- [ ] **Step 2: Córrelo con la API real**

Run: `python scripts/smoke_chat_consulta.py`
Expected, en las 4 preguntas:
- El `crudo` **no** trae cifras, solo marcadores.
- El `texto` trae cifras.
- Ninguna sale «[cifra no disponible]» si el dato existe.
- La Cali sale con una línea por corrida.

Anota en el reporte los tokens de entrada y salida que registra el log (`chat consulta: entrada=…`): sirven para decidir después si conviene Haiku.

- [ ] **Step 3: Compara contra la pantalla**

Abre en la web la corrida de la Calle 13. Comprueba que el total y el capítulo REDES HÚMEDAS coinciden **al peso** con lo que dijo el chat.

- [ ] **Step 4: Navegador**

Con el servidor local (`scripts/servidor_local.py` o la receta de la memoria «Levantar la web en local»):
- El botón aparece abajo a la derecha.
- El panel sigue abierto al cambiar de página.
- Sobrevive a un recargo.
- A 390px de ancho no se sale de la pantalla.
- Sin `ANTHROPIC_API_KEY`, el botón sale deshabilitado.
- El botón **no tapa** los botones de las barras `sticky bottom-0` de `TablaItems.tsx` (~l. 665), `TablaInsumos.tsx` (~l. 271) y `Composicion.tsx` (~l. 736). Si tapa alguno, súbelo (`bottom-16`) o muévelo a la izquierda, y vuelve a probar.
- Pregunta en el chat las cosas que el detector bloquea a propósito («costo calle 13», «precio del insumo 8001») y comprueba que el aviso le dice a la persona cómo reescribir. Si molesta en el uso real, es una decisión aparte (no aflojar el detector compartido sin hablarlo).

- [ ] **Step 5: Commit del smoke**

```bash
git add scripts/smoke_chat_consulta.py
git commit -m "chore: smoke real del chat de consulta"
```

- [ ] **Step 6: Merge y push**

**Pide aprobación explícita** antes de mergear a `master` y de hacer push: `master` despliega solo.
