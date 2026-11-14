"""Contratos internos. No son modelos de entrada de FastAPI ni validadores JWT."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import ContextManager, Protocol
from uuid import UUID


@dataclass(frozen=True)
class Principal:
    sujeto: UUID
    vence: datetime

    def comprobar(self):
        if not isinstance(self.sujeto, UUID) or not isinstance(self.vence, datetime) or self.vence.tzinfo is None:
            raise PermissionError("Identidad no validada")
        if self.vence <= datetime.now(timezone.utc):
            raise PermissionError("Identidad caducada")


class Autenticador(Protocol):
    """Implementacion confiable que verifica firma/emisor/audiencia/vigencia.

    No construir desde claims decodificados sin verificar ni desde user_id del
    cliente. No existe un autenticador de produccion habilitado en esta fase.
    """

    def verificar(self, credencial: str) -> Principal: ...


@dataclass(frozen=True)
class Seguimiento:
    estado_id: UUID
    expediente_id: UUID


@dataclass(frozen=True)
class Reserva:
    seguimiento: Seguimiento
    trabajo_id: UUID
    token: UUID | None = field(repr=False)
    generacion: int
    estado: str


@dataclass(frozen=True)
class Recibo:
    trabajo_id: UUID
    generacion: int
    repetido: bool


class UnidadSeguimiento(Protocol):
    def seguir(self, instancia: str, caso: str, politica: str) -> Seguimiento: ...
    def reservar(self, seguimiento: Seguimiento, clave: UUID, worker: UUID, binding: UUID) -> Reserva: ...
    def leer_caso(self, seguimiento: Seguimiento, binding: UUID) -> dict | None: ...
    def confirmar(self, reserva: Reserva, registros: list[dict], eventos: list[dict], politica: str) -> int: ...
    def exportar(self, instancia: str, binding: UUID) -> dict | None: ...
    def pendientes(self, binding: UUID, limite: int) -> list[dict]: ...
    def procesar_aviso(self, evento: UUID, binding: UUID) -> None: ...


class AlmacenSeguimiento(Protocol):
    def transaccion(self, credencial: str, *, lectura: bool = False) -> ContextManager[UnidadSeguimiento]: ...
