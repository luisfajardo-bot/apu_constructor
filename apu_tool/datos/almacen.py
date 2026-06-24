"""
Fachada de almacenamiento: agrupa las dos bases (precios + APUs).

El resto de la app recibe un Almacen y usa el repo correcto:
    almacen.precios.get_candidatos(...)  # precios.db
    almacen.apus.get_components(...)      # apus.db
Cambiar a un backend de nube = cambiar lo que se instancia aquí, sin tocar el dominio.
"""
from __future__ import annotations

from pathlib import Path

from apu_tool import config
from apu_tool.datos.apus_db import ApusDB
from apu_tool.datos.precios_db import PreciosDB


class Almacen:
    def __init__(self, precios_path: Path | str = config.PRECIOS_DB_PATH,
                 apus_path: Path | str = config.APUS_DB_PATH):
        self.precios = PreciosDB(precios_path)
        self.apus = ApusDB(apus_path)

    def init_schema(self) -> None:
        self.precios.init_schema()
        self.apus.init_schema()

    def reset(self) -> None:
        self.precios.reset()
        self.apus.reset()

    def counts(self) -> dict[str, int]:
        return {**self.precios.counts(), **self.apus.counts()}
