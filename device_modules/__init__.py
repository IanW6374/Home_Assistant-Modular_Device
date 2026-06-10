try:
    from .loader import setup_device
except ImportError:
    from loader import setup_device

__all__ = ["setup_device"]
