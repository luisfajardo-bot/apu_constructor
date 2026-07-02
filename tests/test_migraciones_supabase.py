import re
from pathlib import Path

from apu_tool import config
from apu_tool.interfaz.cli import ESQUEMAS_PG

MIGR = config.PROJECT_ROOT / "supabase" / "migrations"


def test_migrate_pg_aplica_seguridad():
    assert "seguridad.sql" in ESQUEMAS_PG


def test_migraciones_crean_perfiles_antes_del_rls():
    archivos = sorted(p.name for p in MIGR.glob("*.sql"))
    assert "0002_seguridad.sql" in archivos
    assert "0003_auditoria.sql" not in archivos          # su tabla se movió a 0002_seguridad
    crea = next(n for n in archivos
                if re.search(r"create table[^;]*perfiles",
                             (MIGR / n).read_text("utf-8"), re.I | re.S))
    rls = next(n for n in archivos
               if re.search(r"alter table\s+seguridad\.perfiles[^;]*row level security",
                            (MIGR / n).read_text("utf-8"), re.I | re.S))
    assert crea <= rls   # perfiles se crea en un archivo anterior (o igual) al que le aplica RLS
