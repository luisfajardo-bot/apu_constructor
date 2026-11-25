"""Smoke real del chat de consulta: las preguntas del spec contra la base y la API
reales. Solo LEE (el chat no persiste nada).

Uso:  ANTHROPIC_API_KEY=... python scripts/smoke_chat_consulta.py ["pregunta" ...]
Ojo: con DATABASE_URL en el entorno, `Almacen()` lee la base de PRODUCCIÓN. Es lo que
se quiere para tener "La Cali" y "Calle 13", y es seguro porque no se escribe nada.
"""
import logging
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
    # Los tokens por vuelta salen en el log de `consulta_chat` (para decidir si Haiku).
    logging.basicConfig(level=logging.INFO, format="  [log] %(message)s")
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
