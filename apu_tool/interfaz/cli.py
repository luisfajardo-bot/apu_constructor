"""
Interfaz de línea de comandos.

Uso:
    python -m apu_tool.cli seed                   # semilla inicial desde el Excel (guardado)
    python -m apu_tool.cli sample                 # genera una licitación de ejemplo
    python -m apu_tool.cli build <licitacion.xlsx>  # arma APUs y escribe el cuadro
    python -m apu_tool.cli demo                   # seed + ejemplo + build (todo)
    python -m apu_tool.cli status                 # estado de las bases
    python -m apu_tool.cli db check               # chequeo de integridad APU→insumo
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from apu_tool import config
from apu_tool.nucleo.models import MatchStatus
from apu_tool.dominio.pipeline import (
    build_desde_presupuesto,
    ensure_seeded,
    generate_sample,
    get_almacen,
    run_pipeline,
)


def _progress(i: int, total: int, desc: str) -> None:
    print(f"  [{i}/{total}] {desc[:60]}", flush=True)


def _summary(assembled) -> None:
    total_c = sum(a.contractual_total for a in assembled)
    total_k = sum(a.costo_total for a in assembled)
    margen = total_c - total_k
    n_rev = sum(1 for a in assembled if a.status in (MatchStatus.REVIEW, MatchStatus.NEW))
    print("\n--- CUADRO RESUMEN ---")
    print(f"  Ítems:                {len(assembled)}")
    print(f"  Total contractual:    ${total_c:,.0f}")
    print(f"  Total costo:          ${total_k:,.0f}")
    print(f"  Margen:               ${margen:,.0f} "
          f"({(margen/total_c*100) if total_c else 0:.1f}%)")
    print(f"  Requieren revisión:   {n_rev}")


def cmd_seed(args) -> int:
    from apu_tool.datos.seed import seed, SeedExistente
    from apu_tool.datos.almacen import Almacen
    try:
        counts = seed(Almacen(), xlsx_path=Path(args.xlsx) if args.xlsx else None, force=args.force)
    except SeedExistente as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print("Semillado OK:", counts)
    return 0


def cmd_status(args) -> int:
    alm = get_almacen()
    c = alm.counts()
    meta_precios = alm.precios.get_meta()
    meta_apus = alm.apus.get_meta()
    meta = {**meta_precios, **meta_apus}
    print(f"Base de precios: {alm.precios.path}")
    print(f"Base de APUs:    {alm.apus.path}")
    print(f"  Insumos:        {c.get('insumos', 0)}")
    print(f"  Precios:        {c.get('insumo_precios', 0)}")
    print(f"  APUs:           {c.get('apus', 0)}")
    print(f"  Componentes:    {c.get('apu_componentes', 0)}")
    if meta:
        print(f"  Fuente:         {meta.get('fuente', '?')}")
        print(f"  Fecha seed:     {meta.get('fecha_seed', meta.get('fecha_ingesta', '?'))}")
    print(f"  IA:             {'habilitada' if config.ai_available() else 'fallback determinístico'}")
    return 0


def cmd_db_check(args) -> int:
    from apu_tool.dominio import integridad
    rep = integridad.revisar(get_almacen())
    print(f"Huérfanos (código sin insumo): {rep['huerfanos']}")
    print(f"Aproximados (cruce difuso):     {rep['aproximados']}")
    print(f"Ambiguos (código no resuelve):  {rep['ambiguos']}")
    for d in sorted(rep["detalles"], key=lambda x: -x["n"])[:25]:
        print(f"  [{d['calidad']:<10}] {d['codigo']:>7}  x{d['n']:<3}  "
              f"{d['apu_nom'][:30]}" + (f" -> {d['cat_nom'][:30]}" if d['cat_nom'] else ""))
    return 0


def cmd_db_price(args) -> int:
    alm = get_almacen()
    cands = alm.precios.get_candidatos(args.codigo)
    if not cands:
        print(f"No existe el insumo {args.codigo}.")
        return 1
    if len(cands) > 1:
        print(f"⚠ El código {args.codigo} tiene {len(cands)} insumos distintos:")
    for ins in cands:
        print(f"  id={ins.id}  {ins.codigo}  {ins.nombre}")
        print(f"     Unidad: {ins.unidad}   Grupo: {ins.grupo}")
        print(f"     Precio vigente: ${ins.precio:,.0f}   Fuente: {ins.fuente_precio} "
              f"({'confidencial' if ins.es_confidencial else 'público'})")
        hist = alm.precios.price_history(ins.codigo, nombre=ins.nombre)
        if len(hist) > 1:
            print("     Historial:")
            for h in hist:
                flag = " (vigente)" if h["vigente"] else ""
                print(f"       {h['fecha']}  ${h['precio']:,.0f}  {h['fuente']}{flag}")
    return 0


def cmd_db_update_price(args) -> int:
    alm = get_almacen()
    cands = alm.precios.get_candidatos(args.codigo)
    if not cands:
        print(f"No existe el insumo {args.codigo}.")
        return 1
    if len(cands) > 1 and not args.nombre:
        print(f"⚠ El código {args.codigo} es ambiguo ({len(cands)} insumos). "
              f"Repite con --nombre \"<nombre exacto>\":")
        for ins in cands:
            print(f"  - {ins.nombre}")
        return 1
    try:
        alm.precios.set_precio(args.codigo, args.precio,
                               fuente=args.fuente or "ACTUALIZACION MANUAL",
                               nombre=args.nombre)
    except ValueError as e:
        print(str(e))
        return 1
    print(f"Precio actualizado para {args.codigo}"
          + (f" / {args.nombre}" if args.nombre else "") + f" -> ${args.precio:,.0f}")
    print("Los APUs que usan este insumo tomarán el nuevo precio automáticamente.")
    return 0


def cmd_sample(args) -> int:
    ensure_seeded()
    path = generate_sample(n=args.n)
    print(f"Ejemplo de licitación: {path}")
    return 0


def cmd_build(args) -> int:
    ensure_seeded()
    shift = config.SHIFT_NOCTURNO if args.nocturno else config.SHIFT_DIURNO
    print(f"Armando APUs desde: {args.licitacion} (turno por defecto: {shift})")
    assembled, out = run_pipeline(
        args.licitacion, default_shift=shift,
        out_path=Path(args.out) if args.out else None,
        progress=_progress, use_ai=None if not args.no_ai else False,
    )
    _summary(assembled)
    print(f"\nCuadro resumen escrito en: {out}")
    return 0


def cmd_build_ppto(args) -> int:
    print(f"Armando APUs desde el presupuesto (hoja: {args.hoja})…")
    assembled, out = build_desde_presupuesto(
        path=Path(args.xlsx) if args.xlsx else None,
        hoja=args.hoja,
        out_path=Path(args.out) if args.out else None,
        progress=_progress,
        use_ai=None if not args.no_ai else False,
    )
    _summary(assembled)
    print(f"\nCuadro categorizado escrito en: {out}")
    return 0


def cmd_demo(args) -> int:
    print("1) Semillado del histórico…")
    print("  ", ensure_seeded())
    print("2) Generando licitación de ejemplo…")
    sample = generate_sample(n=args.n)
    print("   ", sample)
    print("3) Armando APUs y cuadro resumen…")
    assembled, out = run_pipeline(sample, progress=_progress,
                                  use_ai=None if not args.no_ai else False)
    _summary(assembled)
    print(f"\nCuadro resumen: {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="apu_tool", description="Armador de APUs de obra civil.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pse = sub.add_parser("seed", help="Semillar las bases desde el Excel histórico (guardado).")
    pse.add_argument("--xlsx", help="Ruta al Excel histórico (opcional).")
    pse.add_argument("--force", action="store_true",
                     help="Re-semillar aunque ya haya datos (¡borra cambios manuales!).")
    pse.set_defaults(func=cmd_seed)

    ps = sub.add_parser("status", help="Estado de las bases de datos.")
    ps.set_defaults(func=cmd_status)

    psa = sub.add_parser("sample", help="Generar una licitación de ejemplo.")
    psa.add_argument("-n", type=int, default=15, help="Número de ítems.")
    psa.set_defaults(func=cmd_sample)

    pb = sub.add_parser("build", help="Armar APUs desde una lista de licitación.")
    pb.add_argument("licitacion", help="Archivo .xlsx o .csv de la licitación.")
    pb.add_argument("--out", help="Ruta de salida del cuadro resumen.")
    pb.add_argument("--nocturno", action="store_true", help="Turno por defecto nocturno.")
    pb.add_argument("--no-ai", action="store_true", help="Forzar fallback determinístico.")
    pb.set_defaults(func=cmd_build)

    pp = sub.add_parser("build-ppto",
                        help="Armar APUs desde el presupuesto oficial por capítulos.")
    pp.add_argument("hoja", nargs="?", default="FOR 1-PPTO OFICIAL",
                    help="Nombre de la hoja del presupuesto.")
    pp.add_argument("--xlsx", help="Ruta al Excel del presupuesto "
                    "(o define la variable APU_SOURCE_XLSX).")
    pp.add_argument("--out", help="Ruta de salida del cuadro categorizado.")
    pp.add_argument("--no-ai", action="store_true", help="Forzar fallback determinístico.")
    pp.set_defaults(func=cmd_build_ppto)

    # Grupo de comandos de base de datos.
    pdb = sub.add_parser("db", help="Operaciones sobre la base de datos.")
    dbsub = pdb.add_subparsers(dest="dbcmd", required=True)
    db_ck = dbsub.add_parser("check", help="Chequeo de integridad APU→insumo.")
    db_ck.set_defaults(func=cmd_db_check)
    db_pr = dbsub.add_parser("price", help="Ver el precio de un insumo y su historial.")
    db_pr.add_argument("codigo")
    db_pr.set_defaults(func=cmd_db_price)
    db_up = dbsub.add_parser("update-price", help="Actualizar el precio de un insumo.")
    db_up.add_argument("codigo")
    db_up.add_argument("precio", type=float)
    db_up.add_argument("--fuente", default="")
    db_up.add_argument("--nombre", help="Nombre exacto del insumo (desambigua códigos repetidos).")
    db_up.set_defaults(func=cmd_db_update_price)

    pd = sub.add_parser("demo", help="Seed + ejemplo + build (todo de una).")
    pd.add_argument("-n", type=int, default=15, help="Número de ítems del ejemplo.")
    pd.add_argument("--no-ai", action="store_true", help="Forzar fallback determinístico.")
    pd.set_defaults(func=cmd_demo)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
