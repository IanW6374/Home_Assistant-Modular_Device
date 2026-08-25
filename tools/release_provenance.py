"""Host-side helpers for reproducible release source provenance."""

import re
import subprocess
from pathlib import Path


REVISION_PATTERN = re.compile(r'^[0-9a-f]{40}$')
SOURCE_MARKER = b'IoTMD_SOURCE_REVISION:'


def validate_source_revision(value):
    revision = str(value).strip().lower()
    if not REVISION_PATTERN.fullmatch(revision):
        raise ValueError('source revision must be a full 40-character Git commit')
    return revision


def git_source_revision(root, allow_dirty=False, include_untracked=True):
    """Return a full revision and reject a dirty release tree by default."""
    root = Path(root).resolve()
    try:
        revision = subprocess.check_output(
            ('git', '-C', str(root), 'rev-parse', 'HEAD'), text=True
        ).strip().lower()
        status_command = ['git', '-C', str(root), 'status', '--porcelain']
        if not include_untracked:
            status_command.append('--untracked-files=no')
        status = subprocess.check_output(status_command, text=True).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError('could not determine source revision: ' + str(exc))
    revision = validate_source_revision(revision)
    if status and not allow_dirty:
        raise ValueError('production releases require a clean Git worktree')
    return revision + ('-dirty' if status else '')


def clean_source_revision(value):
    value = str(value).strip().lower()
    dirty = value.endswith('-dirty')
    revision = validate_source_revision(value[:-6] if dirty else value)
    return revision, dirty


def source_marker(revision):
    revision, _dirty = clean_source_revision(revision)
    return SOURCE_MARKER + revision.encode()


def embedded_source_revision(payload):
    """Find the unique source marker within signed artifact content."""
    payload = bytes(payload)
    revisions = set()
    start = 0
    while True:
        index = payload.find(SOURCE_MARKER, start)
        if index < 0:
            break
        candidate = payload[index + len(SOURCE_MARKER):index + len(SOURCE_MARKER) + 40]
        try:
            revisions.add(validate_source_revision(candidate.decode()))
        except (UnicodeError, ValueError):
            pass
        start = index + len(SOURCE_MARKER)
    if not revisions:
        return ''
    if len(revisions) != 1:
        raise ValueError('artifact contains conflicting source revisions')
    return revisions.pop()
