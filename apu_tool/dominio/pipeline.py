"""
Funciones de alto nivel que orquestan el pipeline completo.

Se reutilizan desde la CLI y desde la interfaz gráfica para no duplicar lógica.
"""
from __future__ import annotations

import random
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from apu_tool import config
from apu_tool.dominio.ai_assist import ApuAdvisor
from apu_tool.dominio.assemble import Assembler
from apu_tool.datos.almacen import Almacen
from apu_tool.datos.seed import seed
from apu_tool.dominio.licitacion import read_licitacion, write_sample_licitacion
from apu_tool.nucleo.models import AssembledApu, LicitacionItem
from apu_tool.dominio.presupuesto import read_presupuesto
from apu_tool.dominio.pricing import PricingEngine
from apu_tool.dominio.report import write_report
from apu_tool.dominio.report_categorizado import write_report_categorizado

ProgressCb = Optional[Callable[[int, int, str], None]]


def get_almacen() -> Almacen:
    alm = Almacen()
    alm.init_schema()
    return alm


def db_is_empty(alm: Optional[Almacen] = None) -> bool:
    alm = alm or get_almacen()
    return alm.counts()["apus"] == 0


def ensure_seeded(xlsx_path: Optional[Path] = None) -> dict:
    """Semilla si las bases están vacías; si no, devuelve los conteos actuales."""
    alm = get_almacen()
    if alm.counts()["apus"] == 0 and alm.counts()["insumos"] == 0:
        return seed(alm, xlsx_path=xlsx_path)
    return alm.counts()


def run_pipeline(
    licitacion_path: Path | str,
    default_shift: str = config.SHIFT_DIURNO,
    out_path: Optional[Path] = None,
    progress: ProgressCb = None,
    use_ai: Optional[bool] = None,
) -> tuple[list[AssembledApu], Path]:
    """Lee la lista, arma los APUs y escribe el cuadro resumen."""
    config.ensure_dirs()
    ensure_seeded()
    alm = get_almacen()
    items = read_licitacion(licitacion_path, default_shift=default_shift)
    advisor = ApuAdvisor(enabled=use_ai)
    assembler = Assembler(alm, advisor=advisor)
    assembled = assembler.assemble_all(items, progress=progress)
    if out_path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = config.OUTPUT_DIR / f"cuadro_resumen_{stamp}.xlsx"
    write_report(assembled, out_path)
    return assembled, Path(out_path)


def build_desde_presupuesto(
    path: Optional[Path] = None,
    hoja: str = "FOR 1-PPTO OFICIAL",
    out_path: Optional[Path] = None,
    progress: ProgressCb = None,
    use_ai: Optional[bool] = None,
) -> tuple[list[AssembledApu], Path]:
    """Lee el presupuesto por capítulos, arma/costea cada ítem (por código directo
    cuando se puede) y escribe el cuadro resumen categorizado."""
    config.ensure_dirs()
    ensure_seeded()
    alm = get_almacen()
    src = Path(path) if path else config.detect_source_xlsx()
    if not src or not Path(src).exists():
        raise FileNotFoundError(
            "No se encontró el Excel del presupuesto. Pásalo con --xlsx <ruta> "
            "o define la variable APU_SOURCE_XLSX.")
    items = read_presupuesto(src, hoja=hoja)
    advisor = ApuAdvisor(enabled=use_ai)
    assembler = Assembler(alm, advisor=advisor)
    assembled = assembler.assemble_all(items, progress=progress)
    if out_path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = config.OUTPUT_DIR / f"cuadro_categorizado_{stamp}.xlsx"
    write_report_categorizado(assembled, out_path)
    return assembled, Path(out_path)


# ---------------------------------------------------------------------------
# Generación de un ejemplo de licitación a partir del histórico
# ---------------------------------------------------------------------------
def generate_sample(n: int = 15, margen: float = 0.18, seed: int = 7,
                    out_path: Optional[Path] = None,
                    alm: Optional[Almacen] = None) -> Path:
    """Crea una lista de licitación de ejemplo con una mezcla de casos:
    coincidencias exactas, descripciones reformuladas (dudosas) y actividades nuevas.
    El precio contractual = costo histórico * (1 + margen), para que el cuadro muestre
    márgenes realistas."""
    config.ensure_dirs()
    alm = alm or get_almacen()
    if db_is_empty(alm):
        ensure_seeded()
    rng = random.Random(seed)
    pricing = PricingEngine(alm)

    apus = [a for a in alm.apus.all_apus() if a.shift == config.SHIFT_DIURNO]
    rng.shuffle(apus)
    chosen = apus[:max(1, n - 3)]

    items: list[LicitacionItem] = []
    n_item = 1
    for apu in chosen:
        _, costo = pricing.cost_apu(apu.codigo, apu.shift)
        if costo <= 0:
            continue
        # Alterna entre descripción idéntica y reformulada (para generar dudosos).
        desc = apu.nombre
        if n_item % 3 == 0:
            desc = _reword(apu.nombre, rng)
        items.append(LicitacionItem(
            item=str(n_item), descripcion=desc, unidad=apu.unidad,
            cantidad=round(rng.uniform(10, 500), 2),
            precio_contractual=round(costo * (1 + margen)),
            shift=config.SHIFT_DIURNO,
        ))
        n_item += 1
        if len(items) >= n - 3:
            break

    # Tres actividades "nuevas" sin match claro.
    nuevos = [
        "Suministro e instalación de barrera anti-ruido modular",
        "Construcción de jardinera prefabricada en concreto arquitectónico",
        "Reparación localizada de fisuras con inyección epóxica",
    ]
    for nv in nuevos:
        items.append(LicitacionItem(
            item=str(n_item), descripcion=nv, unidad="M2",
            cantidad=round(rng.uniform(5, 80), 2),
            precio_contractual=round(rng.uniform(50000, 400000)),
            shift=config.SHIFT_DIURNO,
        ))
        n_item += 1

    if out_path is None:
        out_path = config.SAMPLE_DIR / "licitacion_ejemplo.xlsx"
    return write_sample_licitacion(out_path, items)


def _reword(nombre: str, rng: random.Random) -> str:
    """Reformula levemente un nombre para simular una descripción distinta."""
    words = nombre.split()
    if len(words) > 4:
        # quita una palabra intermedia y agrega un prefijo común
        idx = rng.randint(1, len(words) - 2)
        words = words[:idx] + words[idx + 1:]
    prefijos = ["Suministro e instalación de", "Ejecución de", "Obra de"]
    return f"{rng.choice(prefijos)} {' '.join(words).lower()}"
