_log_output = None
_pending = []


def set_log_output(log_output):
    global _log_output
    _log_output = log_output

    while _pending:
        mode, action, data, logtype = _pending.pop(0)
        _log_output(mode, action, data, logtype)


def log_output(mode, action, data, logtype='INFO'):
    if _log_output:
        _log_output(mode, action, data, logtype)
    else:
        _pending.append((mode, action, data, logtype))
