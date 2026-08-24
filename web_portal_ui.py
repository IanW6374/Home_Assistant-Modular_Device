"""Application-owned UI shell for the authenticated device portal.

This separate module keeps portal presentation remotely updateable without
overwriting the recovery-owned ``portal_ui.py`` frozen into core firmware.
"""

import component_versions
from portal_routes import required_role, role_allows


ASSET_VERSION = str(component_versions.RUNTIME_VERSION)


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
    '145deg,var(--accent),var(--accent2))}.brand-copy{min-width:0}.brand-copy>.eyebrow{display:none}'
    '.brand-title{display:block;font-weight:800;white-space:nowrap}.nav-toggle{display:none}'
    '.portal-identity{display:inline-grid;place-items:center;position:relative;width:32px;height:32px;'
    'padding:0;flex:0 0 32px;border:1px solid var(--accent);border-radius:50%;background:var(--bg);'
    'color:var(--accent2);font-size:.7rem;font-weight:850;letter-spacing:.035em;cursor:help}'
    '.portal-identity:hover{background:#e2f2f4}.portal-identity:focus-visible{outline:3px solid '
    'rgba(8,126,139,.22);outline-offset:2px}'
    '.nav-actions{display:flex;align-items:center;justify-content:flex-end;gap:4px;flex-wrap:wrap}'
    '.nav-link{display:inline-flex;align-items:center;padding:7px 10px;border-radius:8px;'
    'color:var(--muted);font-size:.9rem;font-weight:650}.nav-link:hover,.nav-link[aria-current="page"]{'
    'text-decoration:none;background:var(--bg);color:var(--ink)}.nav-actions form{margin:0}'
    '.nav-group{position:relative}.nav-group>.nav-link[aria-haspopup="true"]:after{content:"▾";'
    'margin-left:6px;font-size:.72rem}.nav-dropdown{position:absolute;z-index:10;top:100%;left:0;'
    'display:none;min-width:13rem;padding:7px;border:1px solid var(--line);border-radius:11px;'
    'background:var(--surface);box-shadow:var(--shadow)}.nav-group:last-of-type .nav-dropdown{'
    'right:0;left:auto}.nav-dropdown .nav-link{display:flex;width:100%;white-space:nowrap}'
    '.nav-menu-trigger{border:0;background:transparent;color:var(--muted);font-weight:650}'
    '.nav-menu-trigger:hover,.nav-menu-trigger[aria-current="page"]{background:var(--bg);color:var(--ink)}'
    '.restart-required{display:flex;align-items:center;gap:8px;margin-left:auto;padding:5px 6px 5px 10px;'
    'border:1px solid #efcf92;border-radius:10px;background:#fffaf1;color:#744500;white-space:nowrap}'
    '.restart-required[hidden]{display:none}.restart-required span{font-size:.78rem;font-weight:750}'
    '.restart-required form{margin:0}.restart-required button{padding:6px 9px;font-size:.78rem}'
    '.nav-group:hover>.nav-dropdown,.nav-group:focus-within>.nav-dropdown,'
    '.nav-group.open>.nav-dropdown{display:grid;gap:2px}'
    '.breadcrumb{display:flex;align-items:center;justify-content:flex-end;gap:7px;white-space:nowrap;'
    'margin:0 0 18px;color:var(--muted);font-size:.78rem}.breadcrumb a{color:var(--muted)}'
    '.breadcrumb-separator{color:#91a0a6}'
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
    'label.field{display:grid;gap:6px;margin:8px 0}input,select,textarea,button{'
    'font:inherit;border-radius:9px}input,select,textarea{width:100%;padding:10px 12px;'
    'color:var(--ink);background:var(--bg);border:1px solid var(--line);outline:none}'
    'input:focus,select:focus,textarea:focus{border-color:var(--accent);'
    'box-shadow:0 0 0 3px rgba(8,126,139,.18)}'
    'input[aria-invalid="true"],select[aria-invalid="true"],textarea[aria-invalid="true"]{'
    'border-color:var(--bad);background:#fff7f7;box-shadow:0 0 0 3px rgba(181,51,51,.16)}'
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
    '.button[aria-disabled="true"],.nav-link[aria-disabled="true"]{cursor:not-allowed;'
    'pointer-events:none;border-color:#d3dde1;background:#e7ecee;color:#7b8a91;opacity:1}'
    '.check{display:flex;align-items:center;gap:9px;font-weight:550;margin:9px 0}'
    '.check input{width:1rem;height:1rem;box-shadow:none}.notice,.error,.warning{'
    'border-radius:10px;padding:12px 15px;margin:17px 0;border:1px solid var(--line);'
    'background:var(--surface)}.notice{border-color:var(--good);color:var(--good)}'
    '.error{border-color:var(--bad);color:var(--bad)}.warning{border-color:var(--warn);color:#744500}'
    '.badge{display:inline-flex;align-items:center;border:1px solid var(--line);'
    'border-radius:999px;padding:2px 8px;font-size:.76rem;font-weight:750;'
    'color:var(--muted);background:var(--bg)}.badge.good{color:var(--good)}'
    '.badge.warn{color:var(--warn)}.metrics{display:grid;grid-template-columns:repeat('
    'auto-fit,minmax(10rem,1fr));gap:13px}.metric{border:1px solid var(--line);'
    'border-radius:14px;padding:18px;background:var(--surface);min-width:0;text-align:center}.metric span{'
    'display:block;color:var(--muted);font-size:.73rem;font-weight:700;text-transform:uppercase;'
    'letter-spacing:.06em}.metric strong{display:block;margin-top:5px;overflow-wrap:anywhere}'
    '.metric.good{border-color:#9ed6bd}.metric.warn{border-color:#efcf92}'
    '.metric.wide{grid-column:span 2;min-width:20rem}'
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
    '.log-toolbar select{width:auto}.log-toolbar input{width:7rem}.log-view{white-space:pre-wrap;overflow-wrap:anywhere;'
    'background:#10181c;color:#dce7ef;padding:16px;border-radius:10px;height:42vh;'
    'overflow-y:auto;border:1px solid #304149}.refresh-controls{display:flex;align-items:center;'
    'gap:7px}.refresh-status{justify-content:center;min-width:7rem}.refresh-toggle{min-width:5rem}'
    '.update-summary{display:grid;'
    'grid-template-columns:repeat(auto-fit,minmax(13rem,1fr));gap:13px}'
    '.update-history,.update-summary>p{grid-column:1/-1}.upgrade-grid{display:grid;'
    'grid-template-columns:1fr;gap:17px}.upgrade-grid>.card{margin:0}'
    '.update-actions{display:flex;gap:11px;'
    'align-items:center;flex-wrap:wrap;margin-top:13px}.update-options{display:flex;gap:8px;'
    'align-items:center;flex-wrap:wrap;padding:8px;border:1px solid var(--line);border-radius:9px}'
    '.update-actions.next-stage{justify-content:flex-end}.update-actions.next-stage form{margin-left:auto}'
    '.update-options-label{font-size:.78rem;color:var(--muted)}.update-switch{display:flex;'
    'gap:5px;align-items:center}.update-switch input{width:1rem;height:1rem}'
    '.task-progress{display:flex;align-items:center;justify-content:center;width:100%;gap:9px;'
    'margin:13px 0;color:var(--muted);text-align:center}'
    '.task-progress[hidden]{display:none}.status-spinner{width:1rem;height:1rem;flex:0 0 auto;'
    'border:2px solid var(--line);border-top-color:var(--accent);border-radius:50%;'
    'animation:status-spin .75s linear infinite}.status-text{font-variant-numeric:tabular-nums}'
    '.task-progress.complete .status-spinner,.task-progress.failed .status-spinner{display:none}'
    '.task-progress.complete{color:var(--good)}.task-progress.failed{color:var(--bad)}'
    '.status-history{display:block;margin:8px 0;color:var(--muted);font-size:.82rem}'
    '.status-history.complete{color:var(--good)}.status-history.failed{color:var(--bad)}'
    '.conditional-fields{border:0;padding:0;margin:0;min-width:0}'
    '.conditional-fields[disabled]{opacity:.55}'
    '.field.disabled-field{opacity:.55}#release-check-fields{grid-column:1/-1}'
    '.health-groups{display:grid;grid-template-columns:repeat(auto-fit,minmax(15rem,1fr));gap:11px}'
    '.health-group{border:1px solid var(--line);border-radius:11px;padding:11px;background:var(--soft)}'
    '.health-group h3{margin:0 0 7px}.health-items{display:grid;gap:5px}'
    '.health-item{display:flex;justify-content:space-between;align-items:baseline;gap:11px;'
    'padding:5px 0;border-top:1px solid var(--line)}.health-item:first-child{border-top:0}'
    '.health-item span{font-size:.75rem;color:var(--muted)}.health-item strong{font-size:.88rem;'
    'text-align:right;overflow-wrap:anywhere;min-width:0}'
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
    'font-size:.72rem}.property-row strong{display:block;overflow-wrap:anywhere}'
    '.restore-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(19rem,1fr));gap:11px}'
    '.restore-card{min-width:0;padding:13px;border:1px solid var(--line);border-left-width:5px;'
    'border-radius:11px;background:var(--surface)}.restore-card.same{border-left-color:var(--good);'
    'background:#f4fbf7}.restore-card.changed{border-left-color:var(--warn);background:#fffaf1}'
    '.restore-card.missing{border-left-color:var(--bad);background:#fff7f7}'
    '.restore-card-head{display:flex;align-items:center;justify-content:space-between;gap:8px;'
    'margin-bottom:9px}.restore-card-head strong{font-size:.86rem}.restore-state{font-size:.7rem;'
    'font-weight:800;text-transform:uppercase;letter-spacing:.05em}.restore-card.same .restore-state{'
    'color:var(--good)}.restore-card.changed .restore-state{color:var(--warn)}'
    '.restore-card.missing .restore-state{color:var(--bad)}.restore-value{font-weight:750;'
    'overflow-wrap:anywhere}.restore-compare{display:grid;grid-template-columns:1fr 1fr;gap:8px}'
    '.restore-pane{min-width:0;padding:9px;border:1px solid var(--line);border-radius:8px;'
    'background:rgba(255,255,255,.75)}.restore-pane span{display:block;margin-bottom:3px;'
    'color:var(--muted);font-size:.69rem;font-weight:750;text-transform:uppercase}'
    '.restore-pane strong{display:block;font-size:.82rem;overflow-wrap:anywhere}'
    '.entity-list{display:grid;'
    'gap:7px}.entity-item{border:1px solid var(--line);border-radius:9px;background:var(--surface);'
    'padding:0 11px}.entity-item summary{padding:10px 0}.config-error{color:var(--bad)}'
    '.certificate-group{margin-top:18px;padding-top:2px}.certificate-group+.certificate-group{'
    'border-top:1px solid var(--line);padding-top:18px}.certificate-group-head{margin-bottom:10px}'
    '.certificate-group-head h3{font-size:1.05rem}.certificate-group-head p{margin:3px 0 0}'
    '@media(prefers-reduced-motion:reduce){.status-spinner{animation-duration:1.5s}}'
    '.auth-card{'
    'width:min(28rem,100%);margin:6vh auto;padding:23px}.auth-card form{display:grid;gap:13px}'
    '.auth-card button{width:100%}.setup-main{width:auto;max-width:none;'
    'margin:0 clamp(16px,4vw,38px)}.setup-main>.brand{margin-bottom:13px}'
    '.setup-main button,.setup-main .button{width:100%}'
    '.setup-main .section-title{align-items:center}.setup-main .section-title button.compact{'
    'width:auto;min-width:8rem;flex:0 0 auto;margin-left:auto}'
    '.setup-steps{display:flex;gap:6px;width:100%;margin:0 0 28px}.setup-step{height:5px;flex:1;'
    'border-radius:99px;background:#d7e0e2}.setup-step.active{background:var(--accent)}'
    '@media(max-width:900px){.nav-toggle{display:inline-flex}.nav-actions{display:none;'
    'width:100%;justify-content:flex-start;padding:10px;background:var(--surface);'
    'border:1px solid var(--line);border-radius:12px}.nav-actions.open{display:flex}'
    '.topbar{flex-wrap:wrap}.nav-link{flex:1 0 auto}}'
    '@media(max-width:600px){main{width:auto;margin:0 11px;padding:28px 0 44px}'
    '.brand-title{font-size:.9rem}.page-head{align-items:flex-start;flex-direction:column}'
    '.page-head h1{font-size:2rem}.actions,.controls{align-items:stretch}.actions>*{max-width:100%}'
    '.code-editor{min-height:24rem}.nav-actions{flex-direction:column;align-items:stretch}'
    '.nav-group,.nav-link{width:100%}.nav-actions.open .nav-dropdown{position:static;display:grid;'
    'min-width:0;margin:2px 0 7px 12px;box-shadow:none}.breadcrumb{justify-content:flex-end}'
    '.metric.wide{grid-column:1/-1;min-width:0}'
    '.upgrade-grid{grid-template-columns:1fr}'
    '.card,.panel{padding:18px}.grid{grid-template-columns:1fr}}'
)


PORTAL_JS = (
    '(function(){function invalidField(field,message,report){if(!field)return false;if(message){'
    'field.setCustomValidity(message);field.setAttribute("data-portal-custom-error","1");}'
    'field.setAttribute("aria-invalid","true");var label=field.closest?field.closest("label"):null;'
    'if(!label&&field.id)label=document.querySelector("label[for=\\\""+field.id+"\\\"]");'
    'if(label)label.classList.add("field-invalid");if(report!==false&&field.focus)field.focus();'
    'if(report!==false&&field.reportValidity)'
    'field.reportValidity();return false;}function clearInvalid(field){if(!field)return;if(field.getAttribute('
    '"data-portal-custom-error")){field.setCustomValidity("");field.removeAttribute("data-portal-custom-error");}'
    'if(!field.validity||field.validity.valid){field.removeAttribute("aria-invalid");var label=field.closest?'
    'field.closest("label"):null;if(!label&&field.id)label=document.querySelector("label[for=\\\""+'
    'field.id+"\\\"]");if(label)label.classList.remove("field-invalid");}}window.portalInvalid='
    'invalidField;window.portalRequire='
    'function(field,message){var missing=!field||(field.type==="file"?!field.files||!field.files.length:'
    'field.type==="checkbox"?!field.checked:!String(field.value||"").trim());if(missing)return invalidField('
    'field,message);clearInvalid(field);if(field.validity&&!field.validity.valid)return invalidField(field);'
    'return true;};document.addEventListener("invalid",function(e){invalidField(e.target,null,false);},true);'
    'document.addEventListener("input",function(e){clearInvalid(e.target);},true);document.addEventListener('
    '"change",function(e){clearInvalid(e.target);},true);'
    'var b=document.getElementById("nav-toggle"),n=document.getElementById("portal-nav");'
    'if(b&&n){b.onclick=function(){var o=n.classList.toggle("open");b.setAttribute("aria-expanded",o?"true":"false");};}'
    'var groups=document.querySelectorAll(".nav-group");function close(skip){for(var i=0;i<groups.length;i++){'
    'if(groups[i]===skip)continue;groups[i].classList.remove("open");var x=groups[i].querySelector('
    '".nav-menu-trigger");if(x)x.setAttribute("aria-expanded","false");}}for(var j=0;j<groups.length;j++){'
    'var trigger=groups[j].querySelector(".nav-menu-trigger");if(!trigger)continue;trigger.onclick=function(e){'
    'e.stopPropagation();var group=this.parentNode,open=!group.classList.contains("open");close(group);'
    'group.classList.toggle("open",open);this.setAttribute("aria-expanded",open?"true":"false");};}'
    'document.onclick=function(){close();};document.onkeydown=function(e){if(e.key==="Escape"){close();'
    'if(document.activeElement&&document.activeElement.blur)document.activeElement.blur();}};'
    'var restart=document.getElementById("restart-required");if(restart){fetch("/api/restart-required",'
    '{cache:"no-store",credentials:"same-origin"}).then(function(r){return r.ok?r.json():null;}).then('
    'function(s){if(!s||!s.required)return;restart.hidden=false;var label=document.getElementById('
    '"restart-required-label");if(label&&s.reason_count)label.textContent=s.reason_count===1?'
    '"Restart required":"Restart required ("+s.reason_count+" changes)";}).catch(function(){});}'
    '})();'
)


NAVIGATION = (
    ('status', '/', 'Status', (
        ('overview', '/', 'Overview'),
    )),
    ('system', '/settings', 'System', (
        ('settings', '/settings', 'Network'),
        ('portal_settings', '/portal-settings', 'Portal'),
        ('ntp_settings', '/ntp-settings', 'Time / Date'),
        ('mqtt', '/mqtt', 'MQTT'),
        ('home_assistant', '/home-assistant', 'Home Assistant'),
        ('device_api', '/device-api', 'Device API'),
        ('logging_settings', '/logging-settings', 'Logging'),
    )),
    ('module', '/module-settings', 'Module', (
        ('modules', '/module-settings', 'Configuration'),
        ('module_diagnostics', '/diagnostics', 'Diagnostics'),
    )),
    ('user', '/user', 'User', (
        ('user_settings', '/user', 'Account'),
    )),
    ('maintenance', '/updates', 'Maintenance', (
        ('updates', '/updates', 'Upgrades'),
        ('certificates', '/certificates', 'Certificates'),
        ('configuration_backup', '/configuration-backup', 'Configuration backup'),
        ('health_history', '/health-history', 'Health history'),
        ('logging', '/logging', 'Log viewer'),
        ('factory_default', '/factory-default', 'Factory default'),
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
        '<div class="brand"><span class="brand-mark">HA</span><span class="brand-copy">'
        '<span class="eyebrow">HAMD</span><span class="brand-title">'
        'Home Assistant Modular Device</span></span></div>'
    )


def identity_badge(username, role):
    """Render the authenticated identity without trusting either value."""
    if not username:
        return ''
    tokens = []
    token = ''
    for character in str(username).strip():
        if character.isalnum():
            token += character
        elif token:
            tokens.append(token)
            token = ''
    if token:
        tokens.append(token)
    if len(tokens) > 1:
        initials = tokens[0][0] + tokens[-1][0]
    elif tokens:
        initials = tokens[0][:2]
    else:
        initials = '??'
    role_label = str(role).strip().capitalize() or 'Unknown'
    description = str(username) + ' · ' + role_label + ' privileges'
    return (
        '<div class="portal-identity" tabindex="0" aria-label="Signed in as ' +
        escape(username) + ', ' + escape(role) + '" title="' +
        escape(description) + '"><span aria-hidden="true">' +
        escape(initials.upper()) + '</span></div>'
    )


def _attribute(tag, name):
    """Return a quoted HTML attribute from a trusted renderer tag."""
    marker = str(name) + '='
    offset = tag.find(marker)
    if offset < 0:
        return ''
    offset += len(marker)
    if offset >= len(tag) or tag[offset] not in ('"', "'"):
        return ''
    quote = tag[offset]
    end = tag.find(quote, offset + 1)
    return '' if end < 0 else tag[offset + 1:end]


def _disable_controls(fragment, required):
    explanation = 'Requires ' + str(required).capitalize() + ' privileges'
    for element in ('button', 'input', 'select', 'textarea'):
        marker = '<' + element
        offset = 0
        while True:
            offset = fragment.find(marker, offset)
            if offset < 0:
                break
            end = fragment.find('>', offset)
            if end < 0:
                break
            tag = fragment[offset:end + 1]
            if ' disabled' not in tag:
                tooltip = (
                    '' if ' title=' in tag else
                    ' title="' + escape(explanation) + '"'
                )
                replacement = (
                    tag[:-1] + ' disabled aria-disabled="true"' + tooltip + '>'
                )
                fragment = fragment[:offset] + replacement + fragment[end + 1:]
                offset += len(replacement)
            else:
                offset = end + 1
    return fragment


def restrict_actions(page, role):
    """Disable rendered actions that the current portal role cannot perform."""
    page = str(page)
    if str(role) == 'administrator':
        return page
    offset = 0
    while True:
        start = page.find('<form', offset)
        if start < 0:
            break
        tag_end = page.find('>', start)
        form_end = page.find('</form>', tag_end)
        if tag_end < 0 or form_end < 0:
            break
        tag = page[start:tag_end + 1]
        action = _attribute(tag, 'action')
        required = required_role('POST', action)
        if action and not role_allows(role, required):
            inner = _disable_controls(page[tag_end + 1:form_end], required)
            page = page[:tag_end + 1] + inner + page[form_end:]
            form_end = tag_end + 1 + len(inner)
        offset = form_end + len('</form>')

    # Button-styled links and menu entries are actions too. Removing href keeps
    # keyboard and pointer users from reaching a plain-text authorization page.
    offset = 0
    while True:
        start = page.find('<a ', offset)
        if start < 0:
            break
        end = page.find('>', start)
        if end < 0:
            break
        tag = page[start:end + 1]
        href = _attribute(tag, 'href')
        required = required_role('GET', href)
        if href.startswith('/') and not role_allows(role, required):
            href_token = ' href="' + href + '"'
            replacement = tag.replace(href_token, '', 1)
            if replacement == tag:
                href_token = " href='" + href + "'"
                replacement = tag.replace(href_token, '', 1)
            tooltip = (
                '' if ' title=' in replacement else
                ' title="Requires ' + escape(str(required).capitalize()) +
                ' privileges"'
            )
            replacement = replacement[:-1] + (
                ' aria-disabled="true"' + tooltip + '>'
            )
            page = page[:start] + replacement + page[end + 1:]
            offset = start + len(replacement)
        else:
            offset = end + 1
    return page


def personalise_page(page, username, role):
    """Add request-local identity and permission presentation to portal HTML."""
    page = str(page).replace(
        '<!--portal-identity-->', identity_badge(username, role), 1
    )
    return restrict_actions(page, role)


def navigation(active, csrf):
    links = []
    for key, path, label, children in NAVIGATION:
        child_keys = tuple(item[0] for item in children)
        current = ' aria-current="page"' if key == active or active in child_keys else ''
        child_links = []
        for child_key, child_path, child_label in children:
            child_current = ' aria-current="page"' if child_key == active else ''
            child_links.append(
                '<a class="nav-link" role="menuitem" href="' +
                escape(child_path) + '"' + child_current + '>' +
                escape(child_label) + '</a>'
            )
        links.append(
            '<div class="nav-group"><button class="nav-link nav-menu-trigger" type="button" '
            'aria-haspopup="true" aria-expanded="false"' + current + '>' + escape(label) + '</button>'
            '<div class="nav-dropdown" role="menu" aria-label="' + escape(label) +
            ' submenu">' + ''.join(child_links) + '</div></div>'
        )
    logout = (
        '<form action="/logout" method="post"><input type="hidden" name="csrf" value="' +
        escape(csrf) + '"><button class="secondary compact" type="submit">Sign out</button></form>'
    )
    return (
        '<button id="nav-toggle" class="nav-toggle secondary compact" type="button" '
        'aria-controls="portal-nav" aria-expanded="false">Menu</button>'
        '<nav id="portal-nav" class="nav-actions" aria-label="Primary">' +
        ''.join(links) + logout + '<!--portal-identity--></nav>'
    )


def breadcrumb(active):
    for _key, path, label, children in NAVIGATION:
        for child_key, child_path, child_label in children:
            if child_key != active:
                continue
            return (
                '<div class="breadcrumb" role="navigation" aria-label="Breadcrumb">'
                '<a href="' + escape(path) + '">' + escape(label) + '</a>'
                '<span class="breadcrumb-separator" aria-hidden="true">\\</span>'
                '<a href="' + escape(child_path) + '" aria-current="page">' +
                escape(child_label) + '</a></div>'
            )
    return ''


def shell(title, active, body, csrf='', script='', extra_css='', authenticated=True,
          main_class=''):
    restart = (
        '<div id="restart-required" class="restart-required" role="status" hidden>'
        '<span id="restart-required-label">Restart required</span>'
        '<form action="/restart-device" method="post"><input type="hidden" name="csrf" value="' +
        escape(csrf) + '"><button type="submit">Restart device</button></form></div>'
        if authenticated else ''
    )
    header = '<header class="topbar">' + brand() + restart + (
        navigation(active, csrf) if authenticated else ''
    ) + '</header>'
    return (
        '<!doctype html><html><head><meta name="viewport" '
        'content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer">'
        '<title>' + escape(title) + '</title><link rel="stylesheet" href="/assets/portal.css?v=' +
        escape(ASSET_VERSION) + '">'
        + ('<style>' + extra_css + '</style>' if extra_css else '') +
        '</head><body>' + header + '<main' +
        (' class="' + escape(main_class) + '"' if main_class else '') +
        '>' + (breadcrumb(active) if authenticated else '') + body +
        '</main><script src="/assets/portal.js?v=' +
        escape(ASSET_VERSION) + '"></script>' +
        ('<script>' + script + '</script>' if script else '') + '</body></html>'
    )


def page_heading(eyebrow, title, description, actions=''):
    return (
        '<div class="page-head"><div><span class="eyebrow">' + escape(eyebrow) +
        '</span><h1>' + escape(title) + '</h1><p class="lead">' +
        escape(description) + '</p></div>' + actions + '</div>'
    )


def progress(identifier='task-progress', label='Working…', hidden=False, state=''):
    state = str(state or '')
    return (
        '<div id="' + escape(identifier) + '" class="task-progress' +
        ((' ' + escape(state)) if state else '') + '" role="status" '
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
        'var t=document.getElementById("restart-target").href,n=0,u=new URL(t,location.href);'
        'function go(){window.location.replace(t);}function ready(){fetch(t,{mode:"no-cors",'
        'cache:"no-store",credentials:"omit"}).then(go).catch(function(){n++;setTimeout(ready,'
        'Math.min(5000,1500+n*350));});}if(u.origin===location.origin){setTimeout(ready,2500);}'
        'else{document.querySelector("#restart-progress .status-text").textContent="Reconnecting…";'
        'setTimeout(go,6000);}'
    )
    return shell('HAMD restarting', '', body, script=script, authenticated=False)


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
    return shell('HAMD task', '', body, script=script, authenticated=False)
