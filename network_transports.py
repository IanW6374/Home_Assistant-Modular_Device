"""Optional network-interface adapters used by transport-neutral services."""

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

try:
    import network
except ImportError:
    network = None

try:
    import hardware_platform
except ImportError:
    hardware_platform = None


class NetworkTransport:
    """Lifecycle contract shared by Wi-Fi, Ethernet, and USB interfaces."""

    name = 'network'

    @classmethod
    def supported(cls):
        return False

    async def start(self):
        raise RuntimeError(self.name + ' transport is unavailable')

    async def stop(self):
        return None

    def snapshot(self):
        return {
            'name': self.name, 'supported': self.supported(),
            'active': False, 'connected': False,
        }


class USBNetwork(NetworkTransport):
    """Experimental MicroPython 1.29 USB NCM network interface."""

    name = 'usb-ncm'

    def __init__(self, interface=None):
        self.interface = interface
        self._active = False
        # A capable firmware includes the USB network descriptor before Python
        # starts. Keep its data path down unless signed policy enables it.
        if self.interface is None and self.supported():
            try:
                self.interface = network.USBD_NCM()
                self.interface.active(False)
            except Exception:
                self.interface = None

    @classmethod
    def supported(cls):
        if not network or not hasattr(network, 'USBD_NCM'):
            return False
        if hardware_platform is None:
            return False
        try:
            capability = hardware_platform.usb_ncm_capability()
            return capability.get('usb_ncm_available') is True
        except Exception:
            return False

    async def start(self):
        if not self.supported():
            raise RuntimeError(
                'USB NCM requires a validated platform capability; a '
                'network.USBD_NCM runtime symbol alone is insufficient'
            )
        if self.interface is None:
            self.interface = network.USBD_NCM()
        self.interface.active(True)
        self._active = True
        return self.snapshot()

    async def stop(self):
        if self.interface is not None:
            try:
                self.interface.active(False)
            except Exception:
                pass
        self._active = False

    async def run(self):
        await self.start()
        try:
            while self._active:
                if hasattr(asyncio, 'sleep_ms'):
                    await asyncio.sleep_ms(1000)
                else:
                    await asyncio.sleep(1)
        finally:
            await self.stop()

    def snapshot(self):
        connected = False
        address = ''
        if self.interface is not None:
            try:
                connected = bool(self.interface.isconnected())
            except Exception:
                pass
            try:
                address = str(self.interface.ipconfig('addr4'))
            except Exception:
                pass
        return {
            'name': self.name,
            'supported': self.supported(),
            'active': bool(self._active),
            'connected': connected,
            'address': address,
            'experimental': True,
        }
