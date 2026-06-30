"""Fachada de persistencia que agrupa los tres repositorios SQLite del proyecto.

Centraliza el acceso a datos para que la capa de dominio y de servicio
trabajen con una sola dependencia. Pensado para migración a nube: reemplazar
los tres repos por implementaciones remotas (Protocol ``Repository``) sin tocar
el resto del código.

Uso típico::

    almacen = Almacen()
    almacen.init_schema()
    almacen.precios.insert_insumos([...])
    almacen.apus.insert_apus([...])
    almacen.corridas.get_items(corrida_id)   # repo añadido en feat/web-v1
"""
from __future__ import annotations

from pathlib import Path

from apu_tool import config
from apu_tool.datos.apus_db import ApusDB
from apu_tool.datos.corridas_db import CorridasDB
from apu_tool.datos.precios_db import PreciosDB


class Almacen:
    def __init__(self, precios_path: Path | str = config.PRECIOS_DB_PATH,
                 apus_path: Path | str = config.APUS_DB_PATH,
                 corridas_path: Path | str = config.CORRIDAS_DB_PATH):
        self.precios = PreciosDB(precios_path)
        self.apus = ApusDB(apus_path)
        self.corridas = CorridasDB(corridas_path)

    def init_schema(self) -> None:
        self.precios.init_schema()
        self.apus.init_schema()
        self.corridas.init_schema()

    def reset(self) -> None:
        """Reseteo COMPLETO de las tres bases (uso explícito; borra también corridas)."""
        self.precios.reset()
        self.apus.reset()
        self.corridas.reset()

    def reset_catalogo(self) -> None:
        """Resetea solo el catálogo (precios + apus), preservando las corridas.

        El catálogo se re-siembra desde el Excel fuente; las corridas son estado de
        aplicación del usuario y NO deben borrarse al re-sembrar (regresión: 'las
        corridas se borran después de un rato')."""
        self.precios.reset()
        self.apus.reset()

    def counts(self) -> dict[str, int]:
        return {**self.precios.counts(), **self.apus.counts(), **self.corridas.counts()}
