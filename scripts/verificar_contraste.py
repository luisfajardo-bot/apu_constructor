"""Verifica que los tokens de color de `web/src/index.css` cumplan WCAG 2.1.

No es un test de vitest a propósito: jsdom no resuelve variables CSS ni calcula
contraste, así que un test de front no puede afirmar nada sobre esto. Este script
lee el CSS de verdad, convierte cada `oklch()` a sRGB y hace la cuenta.

Uso:
    python scripts/verificar_contraste.py

Sale con código 1 si algún par no cumple, así que sirve como prueba ejecutable.
Solo mira el bloque `:root` (el tema claro, el único activo: la app no tiene
`ThemeProvider`). El bloque `.dark` se mantiene coherente pero no se verifica
hasta que exista tema oscuro de verdad.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "web" / "src" / "index.css"

# (texto, fondo, mínimo, descripción)
#   4.5 → texto normal (WCAG 1.4.3)
#   3.0 → borde de componente y elemento gráfico (WCAG 1.4.11), y foco (2.4.7)
PARES: list[tuple[str, str, float, str]] = [
    # ── Estructura ──
    ("foreground", "background", 4.5, "texto principal"),
    ("foreground", "card", 4.5, "texto sobre tarjeta"),
    ("muted-foreground", "background", 4.5, "texto secundario"),
    ("muted-foreground", "card", 4.5, "texto secundario sobre tarjeta"),
    ("foreground", "muted", 4.5, "texto sobre fondo tenue (hover de fila)"),
    ("foreground", "accent", 4.5, "texto sobre la superficie de hover"),
    ("muted-foreground", "muted", 4.5, "texto secundario sobre fondo tenue"),
    ("primary-foreground", "primary", 4.5, "texto sobre el primario oscuro"),
    ("input", "card", 3.0, "borde de campo sobre tarjeta"),
    ("input", "background", 3.0, "borde de campo sobre el fondo"),
    ("ring", "background", 3.0, "anillo de foco"),
    ("ring", "card", 3.0, "anillo de foco sobre tarjeta"),
    ("ring", "muted", 3.0, "anillo de foco sobre fondo tenue"),
    ("rail", "card", 3.0, "subrayado de la pestaña activa"),
    # ── El panel del ingreso: fondo --primary en tema claro ──
    ("primary-foreground-muted", "primary", 4.5, "bajada del panel de ingreso"),
    ("rail-on-primary", "primary", 4.5, "subrayado e íconos del panel de ingreso"),
    # ── Significado: dinero y estado ──
    ("revisar", "revisar-surface", 4.5, "«por revisar»"),
    ("revisar", "card", 4.5, "«por revisar» suelto sobre tarjeta"),
    ("margen-pos", "margen-pos-surface", 4.5, "margen positivo"),
    ("margen-pos", "card", 4.5, "margen positivo suelto"),
    ("margen-neg", "margen-neg-surface", 4.5, "margen negativo"),
    ("margen-neg", "card", 4.5, "margen negativo suelto"),
    ("info", "info-surface", 4.5, "congelada / info"),
    ("info", "card", 4.5, "congelada / info suelto"),
    ("destructive", "card", 4.5, "texto de error"),
    ("destructive", "destructive-surface", 4.5, "error sobre su fondo"),
]

# Tokens que deben existir aunque no se les mida contraste (son decorativos).
DECORATIVOS = ["hairline", "primary-border"]


def oklch_a_srgb(L: float, C: float, h: float) -> tuple[float, float, float]:
    """oklch → sRGB con gamma aplicada, cada canal en 0..1."""
    a, b = C * math.cos(math.radians(h)), C * math.sin(math.radians(h))
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_**3, m_**3, s_**3
    canales = (
        4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    )

    def codificar(c: float) -> float:
        c = max(0.0, min(1.0, c))
        return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055

    r, g, b_ = (codificar(c) for c in canales)
    return (r, g, b_)


def luminancia(rgb: tuple[float, float, float]) -> float:
    def lineal(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lineal(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(x: tuple[float, ...], y: tuple[float, ...]) -> float:
    a, b = luminancia(x), luminancia(y)  # type: ignore[arg-type]
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def a_hex(rgb: tuple[float, float, float]) -> str:
    return "#%02X%02X%02X" % tuple(round(c * 255) for c in rgb)


def leer_tokens(texto: str) -> dict[str, tuple[float, float, float]]:
    """Extrae los `--token: oklch(...)` del bloque `:root`."""
    raiz = re.search(r":root\s*\{(.*?)\n\}", texto, re.S)
    if raiz is None:
        raise SystemExit("No encontré el bloque :root en index.css")
    tokens: dict[str, tuple[float, float, float]] = {}
    for nombre, cuerpo in re.findall(r"--([\w-]+):\s*oklch\(([^)]+)\)", raiz.group(1)):
        partes = cuerpo.replace("/", " ").split()
        if len(partes) >= 3:
            tokens[nombre] = (float(partes[0]), float(partes[1]), float(partes[2]))
    return tokens


def main() -> int:
    tokens = leer_tokens(CSS.read_text(encoding="utf-8"))
    rgb = {k: oklch_a_srgb(*v) for k, v in tokens.items()}
    fallas = 0

    faltan = [t for t in DECORATIVOS if t not in rgb]
    if faltan:
        print(f"  FALTA  tokens decorativos sin definir: {', '.join(faltan)}")
        fallas += len(faltan)

    for texto, fondo, minimo, que in PARES:
        ausentes = [f"--{t}" for t in (texto, fondo) if t not in rgb]
        if ausentes:
            print(f"  FALTA  {' y '.join(ausentes)} — {que}")
            fallas += 1
            continue
        r = contraste(rgb[texto], rgb[fondo])
        ok = r >= minimo
        fallas += 0 if ok else 1
        marca = "OK " if ok else "MAL"
        print(
            f"  {r:5.2f}:1  min {minimo:3.1f}  {marca}  {que}"
            f"   [{a_hex(rgb[texto])} sobre {a_hex(rgb[fondo])}]"
        )

    total = len(PARES) + len(DECORATIVOS)
    print(f"\n{total - fallas}/{total} verificaciones pasan (WCAG 2.1, tema claro)")
    if fallas:
        print("Revisá los valores de :root en web/src/index.css.")
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
