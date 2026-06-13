REQUIRED_DEVICE_FIELDS = ('name', 'uuid', 'type')
REQUIRED_TYPE_FIELDS = ('class', 'subclass')
RS485_DATA_TYPES = ('ascii', 'float32', 'int16', 'int32', 'uint16', 'uint32')


def validate_device_config(device_config, device_types):
    errors = []
    uuids = set()

    if not isinstance(device_config, dict):
        return ['device config must be an object']

    devices = device_config.get('devices')
    if not isinstance(devices, list):
        return ['device config must contain a devices list']

    for index, device in enumerate(devices):
        label = _device_label(device, index)
        errors.extend(_validate_device(device, device_types, label, uuids))

    return errors


def _validate_device(device, device_types, label, uuids):
    errors = []

    if not isinstance(device, dict):
        return [label + ': device must be an object']

    for field in REQUIRED_DEVICE_FIELDS:
        if field not in device:
            errors.append(label + ': missing ' + field)

    uuid = device.get('uuid')
    if uuid in uuids:
        errors.append(label + ': duplicate uuid ' + str(uuid))
    elif uuid is not None:
        uuids.add(uuid)

    if not _valid_uuid(uuid):
        errors.append(label + ': uuid must be 4 hex characters')

    device_type = device.get('type', {})
    if not isinstance(device_type, dict):
        errors.append(label + ': type must be an object')
        device_type = {}

    for field in REQUIRED_TYPE_FIELDS:
        if field not in device_type:
            errors.append(label + ': missing type.' + field)

    type_entry = _find_device_type(device, device_types)
    if type_entry is None and 'class' in device_type and 'subclass' in device_type:
        errors.append(label + ': unsupported device type ' +
                      str(device_type.get('class')) + ':' +
                      str(device_type.get('subclass')))

    entities = device.get('entities', {})
    if device_type.get('class') == 'sensor':
        errors.extend(_validate_sensor_entities(device, type_entry, label))
    elif entities and not isinstance(entities, dict):
        errors.append(label + ': entities must be an object')

    return errors


def _validate_sensor_entities(device, type_entry, label):
    errors = []
    entities = device.get('entities')

    if not isinstance(entities, dict) or not entities:
        return [label + ': sensor devices must define entities']

    keys = set()
    supported = None
    if type_entry:
        supported = type_entry['subclass'][device['type']['subclass']]['entities']

    for entity_index in entities:
        entity = entities[entity_index]
        entity_label = label + '.entities.' + str(entity_index)

        if not isinstance(entity, dict):
            errors.append(entity_label + ': entity must be an object')
            continue

        entity_class = entity.get('class')
        if not entity_class:
            errors.append(entity_label + ': missing class')
        elif supported is not None and entity_class not in supported:
            errors.append(entity_label + ': unsupported class ' + str(entity_class))

        key = entity.get('key', entity_class)
        if key in keys:
            errors.append(entity_label + ': duplicate key ' + str(key))
        else:
            keys.add(key)

        if _uses_rs485(device, entity):
            errors.extend(_validate_rs485_entity(entity, entity_label))

    return errors


def _validate_rs485_entity(entity, label):
    errors = []

    if 'address' not in entity and 'memory_address' not in entity:
        errors.append(label + ': missing RS485 address')
    try:
        count = int(entity.get('count', 1))
    except Exception:
        count = 0

    if count < 1:
        errors.append(label + ': count must be greater than 0')

    data_type = entity.get('data_type', entity.get('type', 'uint16'))
    if data_type not in RS485_DATA_TYPES:
        errors.append(label + ': unsupported data_type ' + str(data_type))

    return errors


def _find_device_type(device, device_types):
    device_type = device.get('type', {})
    for type_entry in device_types:
        try:
            if (
                type_entry['class'] == device_type.get('class') and
                device_type.get('subclass') in type_entry['subclass']
            ):
                return type_entry
        except Exception:
            pass
    return None


def _uses_rs485(device, entity):
    return 'rs485' in device or 'address' in entity or 'memory_address' in entity


def _valid_uuid(uuid):
    if not isinstance(uuid, str) or len(uuid) != 4:
        return False
    try:
        int(uuid, 16)
        return True
    except Exception:
        return False


def _device_label(device, index):
    if isinstance(device, dict):
        name = device.get('name')
        uuid = device.get('uuid')
        if name or uuid:
            return 'device[' + str(index) + '] ' + str(name or uuid)
    return 'device[' + str(index) + ']'
