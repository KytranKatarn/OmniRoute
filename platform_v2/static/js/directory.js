let allMembers = [];
let currentFilter = 'all';

// Fetch team directory
fetch('/api/directory')
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            allMembers = data.members;

            // Update stats
            document.getElementById('total-members').textContent = data.statistics.total_members;
            document.getElementById('total-departments').textContent = data.statistics.total_departments;

            // Build department filter
            buildDepartmentFilter(data.departments);

            // Render team
            renderTeam(data.by_department);
        } else {
            document.getElementById('team-directory').innerHTML =
                '<div class="loading" style="color: #FF0000;">Error loading team directory</div>';
        }
    })
    .catch(err => {
        document.getElementById('team-directory').innerHTML =
            '<div class="loading" style="color: #FF0000;">Failed to load team: ' + err.message + '</div>';
    });

function buildDepartmentFilter(departments) {
    const container = document.getElementById('department-chips');

    departments.sort().forEach(dept => {
        const chip = document.createElement('div');
        chip.className = 'dept-chip';
        chip.dataset.dept = dept;
        chip.textContent = dept.toUpperCase();
        chip.onclick = () => filterByDepartment(dept);
        container.appendChild(chip);
    });
}

function filterByDepartment(dept) {
    currentFilter = dept;

    // Update active chip
    document.querySelectorAll('.dept-chip').forEach(chip => {
        chip.classList.toggle('active', chip.dataset.dept === dept);
    });

    // Filter and render
    if (dept === 'all') {
        const byDept = {};
        allMembers.forEach(m => {
            const d = m.department || 'Unassigned';
            if (!byDept[d]) byDept[d] = [];
            byDept[d].push(m);
        });
        renderTeam(byDept);
    } else {
        const filtered = allMembers.filter(m => m.department === dept);
        const byDept = { [dept]: filtered };
        renderTeam(byDept);
    }
}

function renderTeam(byDepartment) {
    const container = document.getElementById('team-directory');
    container.innerHTML = '';

    Object.keys(byDepartment).sort().forEach(dept => {
        const members = byDepartment[dept];

        const section = document.createElement('div');
        section.className = 'department-section';

        const avatarHtml = (member) => {
            const fullName = member.full_name || member.name || 'Agent';
            const avatarUrl = member.avatar_url ||
                'https://api.dicebear.com/7.x/avataaars/svg?seed=' + encodeURIComponent(fullName);
            return '<img src="' + avatarUrl + '" alt="' + fullName + '">';
        };

        let html = '<div class="department-header">' +
            '<div class="department-name">' + dept.toUpperCase() + '</div>' +
            '<div class="department-count">' + members.length + ' MEMBER' + (members.length !== 1 ? 'S' : '') + '</div>' +
            '</div><div class="team-grid">';

        members.forEach(member => {
            html += '<div class="member-card"><div class="member-header">' +
                '<div class="member-avatar">' + avatarHtml(member) + '</div>' +
                '<div class="member-info">' +
                '<div class="member-name">' + (member.full_name || member.name) + '</div>' +
                '<div class="member-pronouns">' + (member.pronouns || 'they/them') + '</div>' +
                '<div class="member-title">' + (member.title || 'Team Member') + '</div>' +
                '<div class="member-department">' + (member.department || 'General') + '</div>' +
                '</div></div>';

            if (member.bio) {
                const bioText = member.bio.substring(0, 200) + (member.bio.length > 200 ? '...' : '');
                html += '<div class="member-bio">' + bioText + '</div>';
            }

            if (member.specialties && member.specialties.length > 0) {
                html += '<div class="member-specialties">';
                member.specialties.slice(0, 5).forEach(s => {
                    html += '<span class="specialty-badge">' + s + '</span>';
                });
                html += '</div>';
            }

            html += '<div class="member-contact">' +
                '\uD83D\uDCE7 <a href="mailto:' + (member.email || 'team@kytranempowerment.com') + '">' +
                (member.email || 'Contact via website') + '</a>';
            if (member.phone) {
                html += '<br>\uD83D\uDCDE <a href="tel:' + member.phone + '">' + member.phone + '</a>';
            }
            html += '</div></div>';
        });

        html += '</div>';
        section.innerHTML = html;
        container.appendChild(section);
    });
}
