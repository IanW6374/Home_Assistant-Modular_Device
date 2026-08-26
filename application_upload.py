"""File-backed application upload adoption without a second bundle copy."""

import app_update
import update_support


async def adopt_bundle(
    path, allow_protected=False, selections=None, progress_callback=None
):
    update_support.acquire_update_lock()
    adopted = False
    try:
        manifest = await app_update.validate_bundle_async(
            path, allow_protected, progress_callback
        )
        if str(path) != app_update.BUNDLE_PATH:
            app_update._replace_file(str(path), app_update.BUNDLE_PATH)
            adopted = True
        state = app_update.stage_bundle(
            app_update.BUNDLE_PATH, allow_protected, selections,
            manifest=manifest
        )
        update_support.record_update_event(
            'application', 'staged', state.get('version', ''),
            digest=str(manifest.get('signature', ''))
        )
        return state
    except Exception as exc:
        if adopted:
            app_update._remove_if_exists(app_update.BUNDLE_PATH)
            app_update._remove_if_exists(app_update.STATE_PATH)
        update_support.record_update_event(
            'application', 'rejected', detail=str(exc)
        )
        raise
    finally:
        update_support.release_update_lock()


async def receive_for_portal(
    reader, content_length, allow_protected, max_bytes, progress_callback=None
):
    if hasattr(reader, 'path'):
        reader.close()
        state = await adopt_bundle(
            reader.path, allow_protected,
            progress_callback=progress_callback
        )
    else:
        state = await app_update.receive_bundle(
            reader, content_length, allow_protected, max_bytes,
            progress_callback=progress_callback
        )
    return (
        'Update ' + str(state.get('version', '')) +
        ' uploaded and verified; choose overwrite options before activation'
    )
