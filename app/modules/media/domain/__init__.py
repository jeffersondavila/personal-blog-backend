"""Dominio de los medios: claves de objeto, validacion de imagen y miniaturas.

Python plano. No importa FastAPI, SQLAlchemy ni el SDK de almacenamiento
(ADR-004; regresion en `tests/unit/test_independencia_del_dominio.py`). Pillow
si entra: es una biblioteca de calculo sobre bytes en memoria, sin E/S ni
framework, igual que lo seria una de criptografia.
"""
