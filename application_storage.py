"""Atomic filesystem operations used by application-slot updates."""

try:
    import ujson as json
except ImportError:
    import json
try:
    import uos as os
except ImportError:
    import os

CHUNK_SIZE = 1024

def _write_stream_file(stream, size, path):
    temp_path = path + '.update-tmp'
    _ensure_parent(path)
    with open(temp_path, 'wb') as output:
        remaining = size
        while remaining:
            chunk = stream.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                raise ValueError('truncated update file: ' + path)
            output.write(chunk)
            remaining -= len(chunk)
    _replace_file(temp_path, path)

def _skip_stream(stream, size, path):
    remaining = size
    while remaining:
        chunk = stream.read(min(CHUNK_SIZE, remaining))
        if not chunk:
            raise ValueError('truncated update file: ' + path)
        remaining -= len(chunk)

def _copy_file(source, destination):
    _ensure_parent(destination)
    temp_path = destination + '.copy-tmp'
    with open(source, 'rb') as src, open(temp_path, 'wb') as dst:
        while True:
            chunk = src.read(CHUNK_SIZE)
            if not chunk:
                break
            dst.write(chunk)
    _replace_file(temp_path, destination)

def _replace_file(source, destination):
    _remove_if_exists(destination)
    os.rename(source, destination)

def _ensure_parent(path):
    parts = path.split('/')[:-1]
    current = ''
    for part in parts:
        current = part if not current else current + '/' + part
        try:
            os.mkdir(current)
        except OSError:
            pass

def _file_exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False

def _read_json(path):
    with open(path, 'rb') as stream:
        return json.loads(stream.read())

def _write_json_atomic(path, value):
    temp_path = path + '.tmp'
    with open(temp_path, 'w') as stream:
        stream.write(json.dumps(value))
    _replace_file(temp_path, path)

def _write_text_atomic(path, value):
    temp_path = path + '.tmp'
    with open(temp_path, 'w') as stream:
        stream.write(str(value))
    _replace_file(temp_path, path)

def _remove_if_exists(path):
    try:
        os.remove(path)
    except OSError:
        pass

def _remove_tree(path):
    try:
        entries = os.listdir(path)
    except OSError:
        return
    for name in entries:
        child = path + '/' + name
        try:
            mode = os.stat(child)[0]
            is_dir = bool(mode & 0x4000)
        except OSError:
            continue
        if is_dir:
            _remove_tree(child)
        else:
            _remove_if_exists(child)
    try:
        os.rmdir(path)
    except OSError:
        pass
