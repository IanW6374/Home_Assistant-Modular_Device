"""Fail-closed adapter for the native transactional namespace ABI."""

import errno

MAX_NAMESPACE_BYTES = 15


class StorageContractError(RuntimeError):
    pass


class StorageConflict(StorageContractError):
    pass


def _generation(value):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise StorageContractError('storage generation is invalid')
    return value


class TransactionalNamespace:
    """One bounded, atomically replaced document in encrypted native NVS."""

    def __init__(self, platform, namespace):
        if (not isinstance(namespace, str) or not namespace or
                len(namespace.encode()) > MAX_NAMESPACE_BYTES):
            raise StorageContractError('storage namespace is invalid')
        for character in namespace:
            if not (
                character in 'abcdefghijklmnopqrstuvwxyz' or
                character in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' or
                character in '0123456789_-'
            ):
                raise StorageContractError('storage namespace is invalid')
        capabilities = platform.capabilities()['storage']
        if not capabilities['encrypted'] or not capabilities['transactional']:
            raise StorageContractError(
                'encrypted transactional storage is unavailable'
            )
        self._maximum = capabilities['max_payload_bytes']
        self._provider = platform.provider
        self._handle = self._provider.storage_open(namespace)
        if not isinstance(self._handle, int) or isinstance(self._handle, bool):
            raise StorageContractError('native storage handle is invalid')
        self._closed = False

    def snapshot(self):
        if self._closed:
            raise StorageContractError('storage namespace is closed')
        value = self._provider.storage_snapshot(self._handle)
        if not isinstance(value, dict) or set(value) != {'generation', 'payload'}:
            raise StorageContractError('native storage snapshot is invalid')
        generation = _generation(value['generation'])
        payload = value['payload']
        if not isinstance(payload, (bytes, bytearray)):
            raise StorageContractError('native storage payload is invalid')
        payload = bytes(payload)
        if len(payload) > self._maximum:
            raise StorageContractError('native storage payload exceeds capability')
        return generation, payload

    def commit(self, generation, payload):
        if self._closed:
            raise StorageContractError('storage namespace is closed')
        generation = _generation(generation)
        if not isinstance(payload, (bytes, bytearray)):
            raise StorageContractError('storage payload must be bytes')
        payload = bytes(payload)
        if len(payload) > self._maximum:
            raise StorageContractError('storage payload exceeds capability')
        try:
            result = self._provider.storage_commit(
                self._handle, generation, payload
            )
        except OSError as exc:
            retry = getattr(errno, 'EAGAIN', 11)
            if exc.args and exc.args[0] in (retry, -retry, 11, -11):
                raise StorageConflict('storage generation changed')
            raise
        result = _generation(result)
        if result != generation + 1:
            raise StorageContractError('native storage generation did not advance')
        return result

    def close(self):
        if not self._closed:
            self._provider.storage_close(self._handle)
            self._closed = True
