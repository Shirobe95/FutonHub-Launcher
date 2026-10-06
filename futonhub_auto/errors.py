class LauncherError(RuntimeError):
    """Base error safe to present to the user."""


class AuthenticationError(LauncherError):
    """El token de GitHub falta, es inválido, ha caducado o no tiene permisos."""


class DownloadError(LauncherError):
    """Fallo de red o de GitHub que puede ser transitorio."""


class RateLimitError(DownloadError):
    """GitHub limitó las peticiones (HTTP 429 o 403 con límite agotado)."""

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class RemoteNotFoundError(LauncherError):
    """El repositorio, la rama o el recurso no existen o el token no los ve."""


class ValidationError(LauncherError):
    pass


class UpdateError(LauncherError):
    pass


class AlreadyRunningError(LauncherError):
    """Otra instancia del launcher está usando la instalación."""
