"""Shared declarative navigation and form metadata for v3 presentation."""


ROLE_LEVEL = {'viewer': 1, 'operator': 2, 'administrator': 3}
MAX_METADATA_ITEMS = 24

NAVIGATION = (
    ('Status', 'Overview', '/status', 'viewer'),
    ('Status', 'Connectivity', '/status/connectivity', 'viewer'),
    ('Device', 'Services', '/device/services', 'viewer'),
    ('Maintenance', 'Diagnostics', '/maintenance/diagnostics', 'operator'),
    ('Maintenance', 'Upgrades', '/maintenance/upgrades', 'administrator'),
)

FORMS = {
    'diagnostic-run': {
        'action': '/maintenance/diagnostics',
        'method': 'POST',
        'role': 'operator',
        'fields': (
            ('target', 'Diagnostic target', 'select', True),
        ),
    },
}


def _level(role):
    return ROLE_LEVEL.get(str(role), 0)


def navigation(role):
    level = _level(role)
    result = []
    for section, label, path, required in NAVIGATION[:MAX_METADATA_ITEMS]:
        if level >= _level(required):
            result.append({
                'section': section, 'label': label, 'path': path,
                'minimum_role': required,
            })
    return result


def form_metadata(name, role):
    value = FORMS.get(str(name))
    if value is None or _level(role) < _level(value['role']):
        return None
    return {
        'action': value['action'], 'method': value['method'],
        'minimum_role': value['role'],
        'fields': [tuple(field) for field in value['fields']],
    }


def html_escape(value):
    return (str(value).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;')
            .replace("'", '&#x27;'))


def render_navigation(role, active_path=''):
    items = []
    for item in navigation(role):
        current = ' aria-current="page"' if item['path'] == active_path else ''
        items.append(
            '<a href="' + html_escape(item['path']) + '"' + current + '>' +
            html_escape(item['label']) + '</a>'
        )
    return '<nav aria-label="Primary">' + ''.join(items) + '</nav>'


def render_form(name, role, options=None):
    metadata = form_metadata(name, role)
    if metadata is None:
        return ''
    fields = []
    options = options or {}
    for field_name, label, field_type, required in metadata['fields']:
        required_text = ' required' if required else ''
        if field_type == 'select':
            values = ''.join(
                '<option value="' + html_escape(value) + '">' +
                html_escape(value) + '</option>'
                for value in options.get(field_name, ())
            )
            control = (
                '<select name="' + html_escape(field_name) + '"' +
                required_text + '>' + values + '</select>'
            )
        else:
            control = (
                '<input name="' + html_escape(field_name) + '" type="' +
                html_escape(field_type) + '"' + required_text + '>'
            )
        fields.append('<label>' + html_escape(label) + control + '</label>')
    return (
        '<form action="' + html_escape(metadata['action']) + '" method="' +
        html_escape(metadata['method'].lower()) + '">' + ''.join(fields) +
        '<button type="submit">Run diagnostic</button></form>'
    )


def render_document(title, role, active_path, content):
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>' + html_escape(title) + '</title></head><body>' +
        render_navigation(role, active_path) + '<main><h1>' +
        html_escape(title) + '</h1>' + content + '</main></body></html>'
    )
