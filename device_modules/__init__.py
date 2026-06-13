try:
    from .loader import setup_device
except ImportError:
    try:
        from loader import setup_device
    except ImportError:
        def setup_device(device, index):
            return None

__all__ = ["setup_device"]
