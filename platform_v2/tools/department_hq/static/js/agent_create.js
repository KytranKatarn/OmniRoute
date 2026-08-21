/* Agent create modal (Roster tab). Own file — the modal is self-contained and
   department-hq.js is already large. Relies on globals defined in
   department-hq.js, which is loaded first: DHQ_BASE, esc(), setHtml(), loadRoster().

   Two agent kinds, both worker_type='ai' underneath the API is NOT how this
   splits — see agSubmit(): 'ai' vs 'internal' maps straight to fields.worker_type.
   'ai'       = dotted acronym identity (F.O.R.G.E.) — name/acronym/acronym_expansion,
                no gender/ethnicity/age.
   'internal' = human-like identity (Terry Caetano) — first/last name, gender,
                ethnicity, age_range, no acronym.

   Mailbox is NOT a side-effect choice. agent_service.create_agent() provisions the
   mailbox unconditionally, best-effort (#5640) — there is nothing a checkbox could
   turn off. side_effects.mailbox is always sent as true so create_agent_full's own
   "mailbox" step (which independently verifies Stalwart provisioning and reports the
   real outcome) always runs and always appears in the per-step results list. */

var AG_KIND_DESC = {
    ai: 'Presents as a dotted acronym (e.g. F.O.R.G.E.) with a plain-language ' +
        'expansion of what the letters stand for. No gender, ethnicity or age — ' +
        'those fields are for human-like agents only.',
    internal: 'Presents as a named person (first + last name) with gender, ' +
        'ethnicity and age range. No acronym — this identity is not an initialism.'
};

function agApplyKind() {
    var kind = document.getElementById('agKind').value;   // 'ai' | 'internal'
    document.getElementById('agAiFields').style.display    = (kind === 'ai') ? '' : 'none';
    document.getElementById('agHumanFields').style.display = (kind === 'ai') ? 'none' : '';
    var desc = document.getElementById('agKindDesc');
    if (desc) desc.textContent = AG_KIND_DESC[kind] || '';
}

// Full reset every time the modal opens — otherwise a cancelled create leaves
// stale values (and stale skill rows) visible on the next open.
function agResetForm() {
    document.getElementById('agKind').value = 'ai';
    ['agName', 'agAcronym', 'agAcronymExp', 'agFirstName', 'agLastName', 'agGender',
     'agEthnicity', 'agAgeRange', 'agDisplayName', 'agTitle', 'agSystemPrompt', 'agBio']
        .forEach(function (id) {
            var e = document.getElementById(id);
            if (e) e.value = '';
        });
    document.getElementById('agDepartment').value = '';
    document.getElementById('agModel').value = 'qwen2.5:7b';
    document.getElementById('agIsDirector').checked = false;
    document.getElementById('agSideBudget').checked = true;
    document.getElementById('agSidePortrait').checked = false;
    document.getElementById('agSkillList').innerHTML = '';
    agApplyKind();
}

function openAgentCreate(prefill) {
    agResetForm();
    document.getElementById('agCreateOverlay').style.display = 'flex';
    document.getElementById('agResults').innerHTML = '';
    if (prefill && prefill.capability) {
        // From approving a pending hiring candidate (Task 9).
        agAddSkillRow(prefill.capability, 3);
        if (prefill.narrative) document.getElementById('agBio').value = prefill.narrative;
    }
}

function closeAgentCreate() {
    document.getElementById('agCreateOverlay').style.display = 'none';
}

function agAddSkillRow(name, level) {
    var wrap = document.getElementById('agSkillList');
    var row = document.createElement('div');
    row.className = 'ag-skill-row';
    var n = document.createElement('input');
    n.type = 'text'; n.className = 'ag-skill-name';
    n.value = name || ''; n.placeholder = 'capability, e.g. code_review';
    var l = document.createElement('select');
    l.className = 'ag-skill-level';
    [1, 2, 3, 4, 5].forEach(function (v) {
        var o = document.createElement('option');
        o.value = v; o.textContent = 'Lv' + v;
        if (v === (level || 1)) o.selected = true;
        l.appendChild(o);
    });
    var x = document.createElement('button');
    x.type = 'button'; x.textContent = '×';
    x.title = 'Remove this skill';
    x.onclick = function () { wrap.removeChild(row); };
    row.appendChild(n); row.appendChild(l); row.appendChild(x);
    wrap.appendChild(row);
}

function agCollectSkills() {
    return [].slice.call(document.querySelectorAll('#agSkillList .ag-skill-row'))
        .map(function (r) {
            return {
                skill_name: r.querySelector('.ag-skill-name').value.trim(),
                proficiency_level: parseInt(r.querySelector('.ag-skill-level').value, 10)
            };
        })
        .filter(function (s) { return s.skill_name; });
}

// Local POST helper instead of the shared apiPost(): apiPost() THROWS on any
// non-2xx status and only preserves a top-level `.error` string from the body —
// it discards the `results` array. create_agent_full's own failure responses
// (e.g. a duplicate name) return 400 WITH a results array and no top-level
// `.error`, so routing through apiPost would silently replace the real
// per-step detail with a generic "POST ... returned 400". That breaks the
// one promise this modal makes: every step, pass or fail, is shown. This
// helper always returns the parsed body regardless of status.
async function agPostJson(path, body) {
    var res = await fetch(DHQ_BASE + path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    });
    var data = null;
    try { data = await res.json(); } catch (_) { /* non-JSON body */ }
    return { status: res.status, data: data };
}

async function agSubmit() {
    var kind = document.getElementById('agKind').value;
    var val = function (id) { var e = document.getElementById(id); return e ? e.value.trim() : ''; };
    var fields = {
        department: val('agDepartment'), title: val('agTitle'), model: val('agModel'),
        system_prompt: val('agSystemPrompt'), bio: val('agBio'),
        worker_type: kind, display_name: val('agDisplayName'),
        is_department_ai: document.getElementById('agIsDirector').checked
    };
    if (kind === 'ai') {
        fields.name = val('agName');
        fields.acronym = val('agAcronym');
        fields.acronym_expansion = val('agAcronymExp');
    } else {
        fields.first_name = val('agFirstName');
        fields.last_name = val('agLastName');
        fields.gender = val('agGender');
        fields.ethnicity = val('agEthnicity');
        fields.age_range = val('agAgeRange');
        fields.name = (fields.first_name + ' ' + fields.last_name).trim();
    }
    if (!fields.display_name) fields.display_name = fields.name;

    var skills = agCollectSkills();
    if (!skills.length) {
        setHtml(document.getElementById('agResults'),
                '<div class="ag-err">At least one skill is required — an agent with no '
              + 'skills is structurally undispatchable.</div>');
        return;
    }

    // mailbox is always true — see the file header comment. It is not a
    // control the operator can toggle; unticking it would change nothing
    // while implying it did.
    var side = {
        budget: document.getElementById('agSideBudget').checked,
        mailbox: true,
        portrait: document.getElementById('agSidePortrait').checked
    };

    var btn = document.getElementById('agSubmit');
    btn.disabled = true;
    try {
        var resp = await agPostJson('/api/roster/agent', { fields: fields, skills: skills, side_effects: side });
        var out = resp.data;
        if (!out) {
            setHtml(document.getElementById('agResults'),
                    '<div class="ag-err">Server returned an unreadable response (HTTP '
                  + resp.status + ').</div>');
            return;
        }
        // EVERY step is shown, pass or fail. A bare "created" would hide a failed skill.
        var rows = (out.results || []).map(function (r) {
            return '<li class="' + (r.ok ? 'ag-ok' : 'ag-fail') + '">'
                 + esc(r.step) + ': ' + (r.ok ? 'ok' : 'FAILED') + ' — ' + esc(r.detail) + '</li>';
        }).join('');
        var headline = out.ok
            ? '<div class="ag-ok">Agent #' + esc(String(out.agent_id)) + ' created</div>'
            : '<div class="ag-err">Not created' + (out.error ? ' — ' + esc(out.error) : '') + '</div>';
        setHtml(document.getElementById('agResults'), headline + (rows ? '<ul>' + rows + '</ul>' : ''));
        if (out.ok && typeof loadRoster === 'function') loadRoster();
    } catch (err) {
        setHtml(document.getElementById('agResults'), '<div class="ag-err">' + esc(err.message) + '</div>');
    } finally {
        btn.disabled = false;
    }
}
