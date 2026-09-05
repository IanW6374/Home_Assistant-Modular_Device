"""Owner-scoped adapter for native platform resource claims."""

import errno


class ResourceError(RuntimeError):
    pass


class ResourceConflict(ResourceError):
    pass


class ResourceManager:
    def __init__(self, platform):
        capabilities = platform.capabilities()['resources']
        if not capabilities['managed']:
            raise ResourceError('native resource management is unavailable')
        self._provider = platform.provider
        self._maximum = capabilities['max_claims']
        self._kinds = tuple(capabilities['kinds'])
        self._claims = {}
        self._claim_contracts = {}
        released = self._provider.resource_reset()
        if not isinstance(released, int) or isinstance(released, bool) or released < 0:
            raise ResourceError('native resource reset result is invalid')

    def claim(self, kind, identifier, owner, shared=False, signature=''):
        if kind not in self._kinds:
            raise ResourceError('resource kind is unsupported')
        key = (kind, identifier, owner)
        if key in self._claims:
            if self._claim_contracts[key] != (bool(shared), str(signature)):
                raise ResourceConflict('resource claim configuration changed')
            return self._claims[key]
        try:
            handle = self._provider.resource_claim(
                kind, identifier, owner, bool(shared), str(signature)
            )
        except OSError as exc:
            busy = getattr(errno, 'EBUSY', 16)
            if exc.args and exc.args[0] in (busy, -busy, 16, -16):
                raise ResourceConflict('resource is already claimed')
            raise
        if not isinstance(handle, int) or isinstance(handle, bool) or handle < 1:
            raise ResourceError('native resource handle is invalid')
        self._claims[key] = handle
        self._claim_contracts[key] = (bool(shared), str(signature))
        return handle

    def construct(self, handle, parameters):
        if handle not in self._claims.values():
            raise ResourceError('resource handle is not owned by this runtime')
        if not isinstance(parameters, dict) or len(parameters) > 12:
            raise ResourceError('resource parameters are invalid')
        result = self._provider.resource_construct(handle, parameters)
        if not isinstance(result, dict) or set(result) != {
                'handle', 'kind', 'state'}:
            raise ResourceError('native resource construction result is invalid')
        if result['handle'] != handle or result['state'] not in (
                'constructed', 'shared'):
            raise ResourceError('native resource construction result is invalid')
        return dict(result)

    def recover(self, handle):
        if handle not in self._claims.values():
            raise ResourceError('resource handle is not owned by this runtime')
        if self._provider.resource_recover(handle) is not True:
            raise ResourceError('native resource recovery failed')
        return True

    def release(self, handle):
        if handle not in self._claims.values():
            raise ResourceError('resource handle is not owned by this runtime')
        self._provider.resource_release(handle)
        for key in tuple(self._claims):
            if self._claims[key] == handle:
                del self._claims[key]
                del self._claim_contracts[key]

    def release_owner(self, owner):
        released = self._provider.resource_release_owner(owner)
        if not isinstance(released, int) or released < 0:
            raise ResourceError('native resource release result is invalid')
        for key in tuple(self._claims):
            if key[2] == owner:
                del self._claims[key]
                del self._claim_contracts[key]
        return released

    def snapshot(self):
        value = self._provider.resource_snapshot()
        if not isinstance(value, (list, tuple)) or len(value) > self._maximum:
            raise ResourceError('native resource snapshot is invalid')
        result = []
        for item in value:
            if not isinstance(item, dict) or set(item) != {
                    'handle', 'kind', 'identifier', 'owner', 'shared',
                    'signature', 'constructed'}:
                raise ResourceError('native resource record is invalid')
            if (not isinstance(item['handle'], int) or
                    isinstance(item['handle'], bool) or item['handle'] < 1):
                raise ResourceError('native resource handle is invalid')
            for key, maximum in (('kind', 12), ('identifier', 32),
                                 ('owner', 32), ('signature', 64)):
                if (not isinstance(item[key], str) or not item[key] or
                        len(item[key]) > maximum):
                    if key != 'signature' or item[key]:
                        raise ResourceError('native resource record is invalid')
            for key in ('shared', 'constructed'):
                if item[key] is not True and item[key] is not False:
                    raise ResourceError('native resource record is invalid')
            result.append(dict(item))
        return result
