"""QOJ VP application shared by the Firefox native helper and local tests."""

__version__ = "0.3.0"

from .application import Application, ApplicationError

__all__ = ["Application", "ApplicationError", "__version__"]
