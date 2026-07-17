"""Excepciones tipadas del parser de estado de cuenta."""

from __future__ import annotations


class StatementParseError(Exception):
    """Error base al parsear un estado de cuenta .xlsx."""


class MalformedStatementError(StatementParseError):
    """El .xlsx no tiene la estructura esperada o faltan secciones/totales."""


class TotalsMismatchError(StatementParseError):
    """Totales declarados no coinciden con la suma de filas (exactitud al centavo)."""


class RowValidationError(StatementParseError):
    """Una fila de posición no cierra: cantidad × precio ≠ total."""
