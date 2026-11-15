"""Errores propios del almacenamiento sintetico. Los mensajes son fijos: nunca incluyen detalles del servidor."""


class AlmacenNoDisponible(RuntimeError):
    """PostgreSQL no responde o la conexion se interrumpio. Es transitorio: se reintenta, no se detiene el monitor."""


class AlmacenIncompatible(RuntimeError):
    """El esquema no es el almacen sintetico esperado (marca ausente, version distinta o permisos excesivos)."""
