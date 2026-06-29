class LauncherError(RuntimeError):
    """Base error safe to present to the user."""


class AuthenticationError(LauncherError):
    pass


class DownloadError(LauncherError):
    pass


class ValidationError(LauncherError):
    pass


class UpdateError(LauncherError):
    pass
