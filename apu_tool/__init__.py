"""
apu_tool — Armador de APUs (Análisis de Precios Unitarios) para obra civil.

Pipeline:
    Excel histórico  ->  base de datos local (SQLite)
    lista de licitación  ->  matching  ->  armado (IA acotada)  ->  precios  ->  cuadro resumen

Frontera de privacidad: la IA nunca recibe valores monetarios. Todo el cálculo
de costo y la comparación contractual vs costo vive en el motor determinístico.
"""

__version__ = "0.1.0"
