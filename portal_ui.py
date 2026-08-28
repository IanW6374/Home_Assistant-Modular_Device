"""Shared, dependency-free UI shell for setup and the authenticated portal."""


ASSET_VERSION = '10'


PORTAL_CSS = (
    ':root{color-scheme:light;--bg:#eef3f5;--surface:#fff;--soft:#f7fafb;'
    '--ink:#17262d;--muted:#61727a;--line:#d8e3e7;--accent:#087e8b;'
    '--accent2:#05606a;--good:#188754;--warn:#a46708;--bad:#b53333;'
    '--shadow:0 12px 34px rgba(17,42,52,.08);--radius:16px}'
    '*{box-sizing:border-box}html{font-size:15px}body{margin:0;min-height:100vh;'
    'font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;'
    'line-height:1.55;color:var(--ink);background:var(--bg)}'
    'a{color:var(--accent);font-weight:700;text-decoration:none}a:hover{text-decoration:underline}'
    '.topbar{position:sticky;z-index:5;top:0;display:flex;align-items:center;'
    'justify-content:space-between;gap:18px;padding:13px clamp(16px,4vw,38px);'
    'border-bottom:1px solid var(--line);background:rgba(255,255,255,.94);'
    'backdrop-filter:blur(10px)}main{width:auto;margin:0 clamp(16px,4vw,38px);'
    'padding:42px 0 68px}.brand{display:flex;align-items:center;'
    'gap:11px;min-width:0;color:var(--ink)}.brand-mark{display:grid;place-items:center;'
    'width:38px;height:38px;flex:0 0 auto;border-radius:11px;color:#fff;'
    'font-size:.68rem;font-weight:850;letter-spacing:.04em;background:linear-gradient('
    '145deg,var(--accent),var(--accent2))}.brand-mark>span{display:block;line-height:.88}'
    '.brand-copy{min-width:0}.brand-copy>.eyebrow{display:none}'
    '.brand-title{display:block;font-weight:800;white-space:nowrap}.nav-toggle{display:none}'
    '.nav-actions{display:flex;align-items:center;justify-content:flex-end;gap:4px;flex-wrap:wrap}'
    '.nav-link{display:inline-flex;align-items:center;padding:7px 10px;border-radius:8px;'
    'color:var(--muted);font-size:.9rem;font-weight:650}.nav-link:hover,.nav-link[aria-current="page"]{'
    'text-decoration:none;background:var(--bg);color:var(--ink)}.nav-actions form{margin:0}'
    '.subnav-wrap{border-bottom:1px solid var(--line);background:var(--surface)}'
    '.subnav{display:flex;align-items:center;gap:5px;width:min(1120px,calc(100% - 32px));'
    'margin:0 auto;padding:8px 0;overflow-x:auto}.subnav-label{padding:6px 10px 6px 0;'
    'color:var(--muted);font-size:.76rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase;'
    'white-space:nowrap}.subnav .nav-link{white-space:nowrap}'
    '.page-head{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;'
    'margin:0 0 28px}.page-head h1{max-width:820px;margin:3px 0 9px;'
    'font-size:clamp(2rem,5vw,3.25rem);line-height:1.05;letter-spacing:-.035em}'
    '.page-head p{max-width:760px;margin:0;font-size:1.02rem}.lead,.muted{color:var(--muted)}'
    '.eyebrow{display:block;margin:0;color:var(--accent);font-size:.74rem;font-weight:800;'
    'letter-spacing:.12em;text-transform:uppercase}.card,.panel{background:var(--surface);'
    'border:1px solid var(--line);border-radius:var(--radius);padding:23px;margin:17px 0;'
    'box-shadow:var(--shadow)}.section-title{display:flex;align-items:flex-end;'
    'justify-content:space-between;gap:16px;margin-bottom:12px}'
    'h1,h2,h3{letter-spacing:-.025em}h1{margin:0}h2{font-size:1.15rem;margin:0 0 10px}'
    'h3{font-size:1rem;margin:0}.section-title h2{margin:0}.grid{display:grid;'
    'grid-template-columns:repeat(auto-fit,minmax(15rem,1fr));gap:8px 17px}'
    '.actions,.controls{display:flex;align-items:center;justify-content:space-between;'
    'gap:9px;flex-wrap:wrap}label{font-weight:700;color:var(--ink)}'
    'label.field{display:grid;gap:6px;margin:8px 0;min-width:0}.field-hint{display:block;'
    'color:var(--muted);font-size:.82rem;font-weight:550;line-height:1.35;overflow-wrap:anywhere}'
    '.field-hint code{white-space:normal;overflow-wrap:anywhere}input,select,textarea,button{'
    'font:inherit;border-radius:9px}input,select,textarea{width:100%;padding:10px 12px;'
    'color:var(--ink);background:var(--bg);border:1px solid var(--line);outline:none}'
    'input:not([type="checkbox"]):not([type="radio"]),select{min-height:46px}'
    '.field[hidden],.conditional-fields[hidden]{display:none}'
    'input:focus,select:focus,textarea:focus{border-color:var(--accent);'
    'box-shadow:0 0 0 3px rgba(8,126,139,.18)}'
    'input[aria-invalid="true"],select[aria-invalid="true"],textarea[aria-invalid="true"]{'
    'border-color:var(--bad);background:#fff7f7;box-shadow:0 0 0 3px rgba(181,51,51,.14)}'
    'label.field-invalid,label.field-invalid .file-button{color:var(--bad)}'
    'button,.button{display:inline-flex;'
    'align-items:center;justify-content:center;gap:6px;padding:10px 14px;'
    'border:1px solid var(--accent);border-radius:9px;background:transparent;'
    'color:var(--accent);font-weight:750;cursor:pointer}button,.button.primary{'
    'background:var(--accent);color:#fff}button:hover,.button.primary:hover{'
    'background:var(--accent2);text-decoration:none}.button:hover{'
    'background:rgba(8,126,139,.08);text-decoration:none}.secondary,button.secondary,'
    '.button.secondary{border-color:var(--accent);background:var(--accent);color:#fff}'
    '.secondary:hover,button.secondary:hover,.button.secondary:hover{border-color:var(--accent2);'
    'background:var(--accent2);color:#fff;text-decoration:none}'
    '.compact,button.compact{padding:7px 10px;font-size:.82rem}.danger,button.danger{'
    'background:var(--bad);border-color:var(--bad);color:#fff}button:disabled{cursor:not-allowed;'
    'border-color:#d3dde1;background:#e7ecee;color:#7b8a91;opacity:1}'
    '.check{display:flex;align-items:center;gap:9px;font-weight:550;margin:9px 0}'
    '.check input{width:1rem;height:1rem;box-shadow:none}.notice,.error,.warning,.info,'
    '.portal-status,.task-progress,.status-history{'
    'border-radius:10px;padding:12px 15px;margin:17px 0;border:1px solid var(--line);'
    'background:var(--surface)}.info,.portal-status,.task-progress,.status-history{'
    'border-color:#91ccd2;color:var(--accent2);background:#f3fbfc}'
    '.notice,.portal-status.success,.task-progress.complete,.status-history.complete{'
    'border-color:var(--good);color:var(--good);background:#f4fbf7}'
    '.error,.portal-status.error,.task-progress.failed,.status-history.failed{'
    'border-color:var(--bad);color:var(--bad);background:#fff7f7}'
    '.warning,.portal-status.warning{border-color:var(--warn);color:#744500;background:#fffaf1}'
    '.portal-status:empty,.status-history:empty{display:none}.actions>.portal-status{flex:1 1 20rem}'
    '.badge{display:inline-flex;align-items:center;border:1px solid var(--line);'
    'border-radius:999px;padding:2px 8px;font-size:.76rem;font-weight:750;'
    'color:var(--muted);background:var(--bg)}.badge.good{color:var(--good)}'
    '.badge.warn{color:var(--warn)}.metrics{display:grid;grid-template-columns:repeat('
    'auto-fit,minmax(10rem,1fr));gap:13px}.metric{border:1px solid var(--line);'
    'border-radius:14px;padding:18px;background:var(--surface);min-width:0;text-align:center}.metric span{'
    'display:block;color:var(--muted);font-size:.73rem;font-weight:700;text-transform:uppercase;'
    'letter-spacing:.06em}.metric strong{display:block;margin-top:5px;overflow-wrap:anywhere}'
    '.metric.good{border-color:#9ed6bd;background:#f4fbf7}.metric.warn{border-color:#efcf92;'
    'background:#fffaf1}.metric.bad{border-color:#e4abab;background:#fff7f7}.metric.info{'
    'border-color:#91ccd2;background:#f3fbfc}'
    '.module-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(17rem,1fr));gap:13px}'
    '.module-card{border:1px solid var(--line);border-radius:14px;padding:18px;'
    'background:var(--surface);min-width:0}.module-head{display:flex;align-items:flex-start;'
    'justify-content:space-between;gap:11px}.module-head p,.module-summary{margin:4px 0}'
    '.state-grid,.diag-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(8rem,1fr));'
    'gap:7px}.state-row,.diag-row{border-top:1px solid var(--line);padding:7px 0;'
    'min-width:0;text-align:center}'
    '.state-row span,.diag-row span{display:block;color:var(--muted);font-size:.72rem}'
    '.state-row strong,.diag-row strong{display:block;overflow-wrap:anywhere}'
    '.published-title{margin:13px 0 7px;color:var(--muted);font-size:.72rem;font-weight:750;'
    'letter-spacing:.05em;text-transform:uppercase}.published-grid{display:grid;'
    'grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));gap:7px}.published-tile{'
    'border:1px solid var(--line);border-radius:9px;padding:9px 10px;background:var(--soft);'
    'min-width:0;text-align:center}'
    '.published-tile span{display:block;color:var(--muted);font-size:.72rem}.published-tile strong{'
    'display:block;overflow-wrap:anywhere}'
    '.diag-tile{border:1px solid var(--line);border-radius:9px;background:var(--soft);'
    'margin-top:11px;padding:11px}.diag-title{color:var(--muted);font-size:.72rem;'
    'text-transform:uppercase;letter-spacing:.04em;font-weight:750}.error-text{'
    'color:var(--bad);overflow-wrap:anywhere}.calibration-form{border-top:1px solid var(--line);'
    'margin-top:11px;padding-top:11px}.log-toolbar{display:flex;align-items:center;gap:9px;'
    'flex-wrap:wrap;margin-bottom:11px}.log-toolbar label{display:flex;align-items:center;gap:7px}'
    '.log-toolbar select{width:auto}.log-view{white-space:pre-wrap;overflow-wrap:anywhere;'
    'background:#10181c;color:#dce7ef;padding:16px;border-radius:10px;height:42vh;'
    'overflow-y:auto;border:1px solid #304149}.update-summary{display:grid;'
    'grid-template-columns:repeat(auto-fit,minmax(13rem,1fr));gap:13px}'
    '.update-history,.update-summary>p{grid-column:1/-1}.update-actions{display:flex;gap:11px;'
    'align-items:center;flex-wrap:wrap;margin-top:13px}.update-options{display:flex;gap:8px;'
    'align-items:center;flex-wrap:wrap;padding:8px;border:1px solid var(--line);border-radius:9px}'
    '.update-options-label{font-size:.78rem;color:var(--muted)}.update-switch{display:flex;'
    'gap:5px;align-items:center}.update-switch input{width:1rem;height:1rem}'
    '.task-progress{display:flex;align-items:center;justify-content:flex-start;width:100%;gap:9px;'
    'margin:13px 0;text-align:left}'
    '.task-progress[hidden]{display:none}.status-spinner{width:1rem;height:1rem;flex:0 0 auto;'
    'border:2px solid var(--line);border-top-color:var(--accent);border-radius:50%;'
    'animation:status-spin .75s linear infinite}.status-text{font-variant-numeric:tabular-nums}'
    '.task-progress.complete .status-spinner,.task-progress.failed .status-spinner{display:none}'
    '.status-history{display:block;margin:8px 0;font-size:.82rem}'
    '@keyframes status-spin{to{transform:rotate(360deg)}}.page-load-action{display:flex;'
    'justify-content:center;width:100%;margin:18px 0 0}.file-input-hidden{position:absolute;'
    'width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);'
    'white-space:nowrap;border:0}.file-button{cursor:pointer}.file-name{color:var(--muted);'
    'overflow-wrap:anywhere}.code-editor{min-height:30rem;font:13px ui-monospace,'
    'SFMono-Regular,Consolas,monospace;line-height:1.45;tab-size:2}.view-switch{display:flex;'
    'gap:5px;padding:4px;border:1px solid var(--line);border-radius:11px;background:var(--soft)}'
    '.view-switch button{border:0;background:transparent;color:var(--muted)}'
    '.view-switch button[aria-selected="true"]{background:var(--surface);color:var(--ink);'
    'box-shadow:0 2px 8px rgba(17,42,52,.08)}.config-preview{display:grid;gap:13px}'
    '.config-module{border:1px solid var(--line);border-radius:14px;padding:18px;background:var(--soft)}'
    '.config-module>.module-head{margin-bottom:12px}.config-block{border-top:1px solid var(--line);'
    'padding:10px 0}.config-block summary{cursor:pointer;font-weight:750}.config-block[open]>summary{'
    'margin-bottom:9px}.property-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(12rem,1fr));'
    'gap:7px}.property-row{min-width:0;padding:8px 10px;border:1px solid var(--line);'
    'border-radius:9px;background:var(--surface)}.property-row span{display:block;color:var(--muted);'
    'font-size:.72rem}.property-row strong{display:block;overflow-wrap:anywhere}.entity-list{display:grid;'
    'gap:7px}.entity-item{border:1px solid var(--line);border-radius:9px;background:var(--surface);'
    'padding:0 11px}.entity-item summary{padding:10px 0}.config-error{color:var(--bad)}.auth-card{'
    'width:min(28rem,100%);margin:6vh auto;padding:23px}.auth-card form{display:grid;gap:13px}'
    '.auth-card button{width:100%}.setup-main{width:auto;max-width:none;'
    'margin:0 clamp(16px,4vw,38px)}.setup-main label.field{margin:.7rem 0}'
    '.setup-main button,.setup-main .button{width:100%}'
    '.setup-main .section-title{align-items:center}.setup-main .section-title button.compact{'
    'width:auto;min-width:8rem;flex:0 0 auto;margin-left:auto}'
    '.setup-steps{display:flex;gap:6px;width:100%;'
    'margin:0 0 28px}.setup-step{height:5px;flex:1;'
    'border-radius:99px;background:#d7e0e2}.setup-step.active{background:var(--accent)}'
    '.credential-group{margin:14px 0;padding:15px;border:1px solid var(--line);'
    'border-radius:12px;background:var(--soft)}.credential-group h3{margin-bottom:3px}'
    '.credential-group>p{margin:0 0 8px}.credential-pair{display:grid;'
    'grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 17px}'
    '.certificate-group{margin-top:18px;padding-top:2px}.certificate-group+.certificate-group{'
    'border-top:1px solid var(--line);padding-top:18px}.certificate-group-head{margin-bottom:10px}'
    '.certificate-group-head h3{font-size:1.05rem}.certificate-group-head p{margin:3px 0 0}'
    '.setup-application-status{display:flex;align-items:center;justify-content:flex-end;'
    'align-self:center;margin-left:auto}'
    '.tooltip-badge{position:relative;cursor:help}.tooltip-badge:after{position:absolute;z-index:20;'
    'top:calc(100% + 8px);right:0;width:max-content;max-width:min(24rem,75vw);padding:8px 10px;'
    'border-radius:8px;background:var(--ink);color:#fff;box-shadow:var(--shadow);content:attr(data-tooltip);'
    'font-size:.78rem;font-weight:600;line-height:1.4;white-space:normal;opacity:0;visibility:hidden;'
    'transform:translateY(-3px);transition:opacity .12s ease,transform .12s ease}'
    '.tooltip-badge:hover:after,.tooltip-badge:focus:after{opacity:1;visibility:visible;transform:none}'
    '@media(prefers-reduced-motion:reduce){.status-spinner{animation-duration:1.5s}'
    '.tooltip-badge:after{transition:none}}'
    '@media(max-width:900px){.nav-toggle{display:inline-flex}.nav-actions{display:none;'
    'width:100%;justify-content:flex-start;padding:10px;background:var(--surface);'
    'border:1px solid var(--line);border-radius:12px}.nav-actions.open{display:flex}'
    '.topbar{flex-wrap:wrap}.nav-link{flex:1 0 auto}}'
    '@media(max-width:600px){main{width:auto;margin:0 11px;padding:28px 0 44px}'
    '.brand-title{font-size:.9rem}.page-head{align-items:flex-start;flex-direction:column}'
    '.page-head h1{font-size:2rem}.actions,.controls{align-items:stretch}.actions>*{max-width:100%}'
    '.code-editor{min-height:24rem}.nav-actions{flex-direction:column;align-items:stretch}'
    '.nav-link{width:100%}.card,.panel{padding:18px}.grid,.credential-pair{'
    'grid-template-columns:1fr}}'
)


PORTAL_JS = (
    '(function(){function invalidField(field,message,report){if(!field)return false;if(message){'
    'field.setCustomValidity(message);field.setAttribute("data-portal-custom-error","1");}'
    'field.setAttribute("aria-invalid","true");var label=field.closest?field.closest("label"):null;'
    'if(!label&&field.id)label=document.querySelector("label[for=\\\""+field.id+"\\\"]");'
    'if(label)label.classList.add("field-invalid");if(report!==false&&field.focus)field.focus();'
    'if(report!==false&&field.reportValidity)field.reportValidity();return false;}'
    'function clearInvalid(field){if(!field)return;if(field.getAttribute("data-portal-custom-error")){'
    'field.setCustomValidity("");field.removeAttribute("data-portal-custom-error");}'
    'if(!field.validity||field.validity.valid){field.removeAttribute("aria-invalid");var label=field.closest?'
    'field.closest("label"):null;if(!label&&field.id)label=document.querySelector("label[for=\\\""+'
    'field.id+"\\\"]");if(label)label.classList.remove("field-invalid");}}window.portalInvalid=invalidField;'
    'window.portalClearInvalid=clearInvalid;'
    'window.portalRequire=function(field,message){var missing=!field||(field.type==="file"?!field.files||'
    '!field.files.length:field.type==="checkbox"?!field.checked:!String(field.value||"").trim());'
    'if(missing)return invalidField(field,message);clearInvalid(field);if(field.validity&&!field.validity.valid)'
    'return invalidField(field);return true;};document.addEventListener("invalid",function(e){'
    'invalidField(e.target,null,false);},true);document.addEventListener("input",function(e){'
    'clearInvalid(e.target);},true);document.addEventListener("change",function(e){clearInvalid(e.target);},true);'
    'window.portalStatus=function(element,state,message){if(!element)return;element.className="portal-status"+'
    '(state?" "+state:"");element.setAttribute("role",state==="error"?"alert":"status");'
    'element.setAttribute("aria-live",state==="error"?"assertive":"polite");if(message!==undefined)'
    'element.textContent=message;};'
    'var b=document.getElementById("nav-toggle"),n=document.getElementById("portal-nav");'
    'if(b&&n){b.onclick=function(){var o=n.classList.toggle("open");b.setAttribute("aria-expanded",o?"true":"false");};}'
    '})();'
)


NAVIGATION = (
    ('overview', '/', 'Overview', ()),
    ('configuration', '/settings', 'Configuration', (
        ('settings', '/settings', 'Device & network'),
        ('modules', '/module-settings', 'Modules'),
        ('home_assistant', '/home-assistant', 'Home Assistant'),
    )),
    ('maintenance', '/updates', 'Security & maintenance', (
        ('updates', '/updates', 'Updates'),
        ('diagnostics', '/diagnostics', 'Diagnostics'),
        ('certificates', '/certificates', 'Certificates'),
    )),
)


def escape(value):
    value = str(value)
    for old, new in (
        ('&', '&amp;'), ('<', '&lt;'), ('>', '&gt;'),
        ('"', '&quot;'), ("'", '&#39;')
    ):
        value = value.replace(old, new)
    return value


def brand():
    return (
        '<div class="brand"><span class="brand-mark" aria-label="IoTMD">'
        '<span aria-hidden="true">IoT</span><span aria-hidden="true">MD</span></span>'
        '<span class="brand-copy">'
        '<span class="eyebrow">IoTMD</span><span class="brand-title">'
        'IoT Modular Device</span></span></div>'
    )


def navigation(active, csrf):
    links = []
    for key, path, label, children in NAVIGATION:
        child_keys = tuple(item[0] for item in children)
        current = ' aria-current="page"' if key == active or active in child_keys else ''
        links.append(
            '<a class="nav-link" href="' + escape(path) + '"' + current + '>' +
            escape(label) + '</a>'
        )
    links.append(
        '<form action="/logout" method="post"><input type="hidden" name="csrf" value="' +
        escape(csrf) + '"><button class="secondary compact" type="submit">Sign out</button></form>'
    )
    return (
        '<button id="nav-toggle" class="nav-toggle secondary compact" type="button" '
        'aria-controls="portal-nav" aria-expanded="false">Menu</button>'
        '<nav id="portal-nav" class="nav-actions" aria-label="Primary">' +
        ''.join(links) + '</nav>'
    )


def secondary_navigation(active):
    for _key, _path, label, children in NAVIGATION:
        child_keys = tuple(item[0] for item in children)
        if active not in child_keys:
            continue
        links = []
        for child_key, child_path, child_label in children:
            current = ' aria-current="page"' if child_key == active else ''
            links.append(
                '<a class="nav-link" href="' + escape(child_path) + '"' + current + '>' +
                escape(child_label) + '</a>'
            )
        return (
            '<div class="subnav-wrap"><nav class="subnav" aria-label="' +
            escape(label) + '"><span class="subnav-label">' + escape(label) +
            '</span>' + ''.join(links) + '</nav></div>'
        )
    return ''


def shell(title, active, body, csrf='', script='', extra_css='', authenticated=True,
          main_class=''):
    header = (
        '<header class="topbar">' + brand() +
        (navigation(active, csrf) if authenticated else '') + '</header>'
    )
    return (
        '<!doctype html><html><head><meta name="viewport" '
        'content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer">'
        '<title>' + escape(title) + '</title><link rel="stylesheet" href="/assets/portal.css?v=' +
        ASSET_VERSION + '">'
        + ('<style>' + extra_css + '</style>' if extra_css else '') +
        '</head><body>' + header +
        (secondary_navigation(active) if authenticated else '') + '<main' +
        (' class="' + escape(main_class) + '"' if main_class else '') +
        '>' + body + '</main><script src="/assets/portal.js?v=' + ASSET_VERSION + '"></script>' +
        ('<script>' + script + '</script>' if script else '') + '</body></html>'
    )


def page_heading(eyebrow, title, description, actions=''):
    return (
        '<div class="page-head"><div><span class="eyebrow">' + escape(eyebrow) +
        '</span><h1>' + escape(title) + '</h1><p class="lead">' +
        escape(description) + '</p></div>' + actions + '</div>'
    )


def progress(identifier='task-progress', label='Working…', hidden=False):
    return (
        '<div id="' + escape(identifier) + '" class="task-progress" role="status" '
        'aria-live="polite"' + (' hidden' if hidden else '') +
        '><span class="status-spinner" aria-hidden="true"></span>'
        '<span class="status-text">' + escape(label) + '</span></div>'
    )


def restart_page(target, message='Settings saved. The device is restarting.'):
    target = str(target or '/login')
    body = (
        '<section class="auth-card card"><span class="eyebrow">Applying changes</span>'
        '<h1>Device restarting</h1><p class="lead">' + escape(message) + '</p>' +
        progress('restart-progress', 'Waiting for portal…') +
        '<p class="muted">The login page will open automatically when the device is ready.</p>'
        '<div class="page-load-action"><a id="restart-target" class="button secondary" href="' +
        escape(target) + '">Open login page</a></div></section>'
    )
    script = (
        'var t=document.getElementById("restart-target").href,a=new URL("/assets/portal.css",t).href,'
        'same=new URL(t).origin===location.origin,offline=false,failures=0,started=Date.now(),'
        'status=document.querySelector("#restart-progress .status-text");'
        'function go(){var join=t.indexOf("?")<0?"?":"&";window.location.replace('
        't+join+"reconnect="+Date.now());}function fresh(url){var u=new URL(url);'
        'u.searchParams.set("restart_probe",Date.now());return u.href;}function probe(url,marker){return fetch(fresh(url),{'
        'mode:same?"same-origin":"no-cors",cache:"no-store",credentials:"omit"}).then(function(r){'
        'if(!same)return true;if(!r.ok)return false;return r.text().then(function(body){'
        'return body.indexOf(marker)>=0;});});}function retry(){setTimeout(ready,offline?2000:500);}'
        'function ready(){if(!offline){probe(t,"id=\\\"login-form\\\"").then(function(ok){if(!ok)throw Error();failures=0;'
        'if(Date.now()-started>=6000){offline=true;status.textContent="Checking restarted portal…";}'
        'else status.textContent="Waiting for device to restart…";retry();}).catch(function(){failures++;'
        'if(failures>=2){offline=true;status.textContent="Device offline — reconnecting…";}retry();});'
        'return;}Promise.all([probe(t,"id=\\\"login-form\\\""),probe(a,":root{")]).then(function(ok){'
        'if(ok[0]&&ok[1]){status.textContent="Portal ready — opening login…";setTimeout(go,500);return;}'
        'status.textContent="Portal starting — reconnecting…";retry();}).catch(function(){retry();});}'
        'setTimeout(ready,1000);'
    )
    return shell('IoTMD restarting', '', body, script=script, authenticated=False)


def task_page(task_id, title, return_url='/updates'):
    body = (
        '<section class="auth-card card"><span class="eyebrow">Device task</span><h1>' +
        escape(title) + '</h1>' + progress('task-progress', 'Starting…') +
        '<div class="page-load-action"><a id="task-return" class="button secondary" href="' +
        escape(return_url) + '" hidden>Continue</a></div></section>'
    )
    script = (
        'var i=' + repr(str(task_id)) + ',b=document.getElementById("task-progress"),'
        'l=b.querySelector(".status-text"),'
        'r=document.getElementById("task-return");function poll(){fetch("/task-status?id="+encodeURIComponent(i),'
        '{cache:"no-store",credentials:"same-origin"}).then(function(x){if(x.status===401){location.replace("/login");'
        'return null;}return x.json();}).then(function(s){if(!s)return;var status=s.message||s.phase||"Working…";'
        'if(typeof s.percent==="number"){status+=" · "+s.percent+"%";}l.textContent=status;'
        'if(s.phase==="complete"||s.phase==="failed"){b.classList.add(s.phase);r.hidden=false;'
        'if(s.phase==="complete"){setTimeout(function(){location.replace(r.href);},900);}return;}setTimeout(poll,600);'
        '}).catch(function(){setTimeout(poll,1200);});}poll();'
    )
    return shell('IoTMD task', '', body, script=script, authenticated=False)
