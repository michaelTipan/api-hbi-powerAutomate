class GraphConfigError(Exception):
    """Faltan variables de entorno o la configuracion de Graph no es usable."""


class ExtractIndexError(Exception):
    """Error de dominio del índice de extractos."""


class ExtractIndexSchemaError(ExtractIndexError):
    """Esquema de lista incompatible o incompleto."""


class DocumentMutationForbidden(ExtractIndexError):
    """Intento de mutación sobre el árbol documental (fail-closed)."""


class UnauthorizedListWriteError(ExtractIndexError):
    """Escritura a una lista fuera de la allowlist del índice."""


class ExtractIndexDuplicateDocKeyError(ExtractIndexError):
    """Existen múltiples filas con el mismo DOC_KEY."""

