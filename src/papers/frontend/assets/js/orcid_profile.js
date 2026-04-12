$(document).ready(function () {
    // Vincular el botón de error para que abra el modal de ajustes real
    $('#btnOpenSettingsFromError').on('click', function () {
        $('#settingsBtn').trigger('click');
    });

    // FIX SEGURO DE DESCARGAS: Evita la condición de carrera con ui.js
    // Esperamos 800ms para asegurar que ui.js y workspace.js inyectaron los HTML y templates
    setTimeout(() => {
        if (typeof restoreTasks === 'function') {
            restoreTasks();
        }
    }, 800);

    // Arrancar la obtención de datos
    loadProfileData();
});

function loadProfileData() {
    $.ajax({
        url: '/api/v1/orcid/profile',
        type: 'GET',
        success: function (profile) {
            $('#orcid-loading').addClass('hidden');
            $('#orcid-content').removeClass('hidden');

            renderHeader(profile);
            renderBioAndKeywords(profile);
            renderLinks(profile);
            renderAffiliations(profile);
            renderWorks(profile);
        },
        error: function (err) {
            $('#orcid-loading').addClass('hidden');
            $('#orcid-error').removeClass('hidden').addClass('flex');
            const msg = (err.status === 403) 
                ? "ORCID synchronization is disabled. Please check your settings." 
                : "We couldn't retrieve your academic profile. Verify your ORCID iD.";
            $('#orcid-error-text').text(msg);
        }
    });
}

function renderHeader(profile) {
    $('#prof-name').text(profile.full_name);
    $('#prof-orcid-link')
        .text(profile.orcid_id)
        .attr('href', `https://orcid.org/${profile.orcid_id}`);
    
    const syncDot = $('#prof-sync-indicator');
    if (profile.sync_status === 'updated') {
        syncDot.addClass('bg-green-500').removeClass('bg-slate-300');
    } else {
        syncDot.addClass('bg-blue-500').removeClass('bg-slate-300');
    }
}

function renderBioAndKeywords(profile) {
    if (profile.biography) {
        $('#prof-bio-section').removeClass('hidden');
        $('#prof-bio').text(profile.biography);
    }
    if (profile.keywords && profile.keywords.length > 0) {
        $('#prof-keywords-section').removeClass('hidden');
        const kwContainer = $('#prof-keywords').empty();
        profile.keywords.forEach(kw => {
            kwContainer.append(`<span class="px-2.5 py-1 bg-slate-100 border border-slate-200 text-slate-600 rounded-md text-xs font-medium">${kw}</span>`);
        });
    }
}

function renderLinks(profile) {
    if (profile.researcher_urls && profile.researcher_urls.length > 0) {
        $('#prof-links-section').removeClass('hidden');
        const ul = $('#prof-links').empty();
        profile.researcher_urls.forEach(link => {
            ul.append(`<li><a href="${link.url}" target="_blank" class="text-blue-600 hover:underline flex items-center gap-1"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path></svg>${link.name || link.url}</a></li>`);
        });
    }
}

function renderAffiliations(profile) {
    const affiliations = [];
    if (profile.employments) affiliations.push(...profile.employments.map(a => ({...a, type: 'Employment'})));
    if (profile.educations) affiliations.push(...profile.educations.map(a => ({...a, type: 'Education'})));
    
    if (affiliations.length > 0) {
        $('#prof-affiliations-section').removeClass('hidden');
        const container = $('#prof-affiliations').empty();
        affiliations.sort((a, b) => (parseInt(b.start_year) || 0) - (parseInt(a.start_year) || 0));

        affiliations.forEach(aff => {
            const dateStr = aff.start_year ? `${aff.start_year} - ${aff.end_year || 'Present'}` : 'N/A';
            container.append(`
                <div class="bg-white p-4 rounded-lg border border-slate-200 flex justify-between items-center shadow-sm">
                    <div>
                        <h4 class="font-bold text-slate-800 text-sm">${aff.role}</h4>
                        <p class="text-xs text-slate-500">${aff.organization}</p>
                    </div>
                    <div class="text-right flex flex-col items-end">
                        <span class="text-[10px] uppercase font-bold px-2 py-0.5 rounded-full ${aff.type === 'Employment' ? 'bg-blue-50 text-blue-600' : 'bg-purple-50 text-purple-600'}">${aff.type}</span>
                        <p class="text-[10px] text-slate-400 mt-1 font-mono">${dateStr}</p>
                    </div>
                </div>
            `);
        });
    }
}

function renderWorks(profile) {
    if (profile.works && profile.works.length > 0) {
        $('#prof-works-section').removeClass('hidden');
        $('#prof-works-count').text(profile.works.length);
        const container = $('#prof-works').empty();
        
        const works = [...profile.works].sort((a, b) => (parseInt(b.publication_year) || 0) - (parseInt(a.publication_year) || 0));

        works.forEach(work => {
            let idsHtml = '';
            if (work.external_ids) {
                work.external_ids.forEach(ext => {
                    // SIEMPRE forzar el enlace cuando es DOI
                    if (ext.type.toLowerCase() === 'doi') {
                        const url = ext.url || `https://doi.org/${ext.value}`;
                        idsHtml += `<a href="${url}" target="_blank" class="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-blue-50 border border-blue-100 text-blue-700 text-xs font-mono hover:bg-blue-100 transition-colors">DOI: ${ext.value}</a>`;
                    } else {
                        idsHtml += `<span class="inline-flex items-center px-2 py-0.5 rounded bg-slate-50 border border-slate-200 text-slate-500 text-xs font-mono">${ext.type.toUpperCase()}: ${ext.value}</span>`;
                    }
                });
            }

            container.append(`
                <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm hover:border-blue-300 transition-colors group">
                    <h3 class="font-bold text-slate-900 group-hover:text-blue-700 leading-snug">${work.title}</h3>
                    ${work.journal_title ? `<p class="text-xs text-slate-500 mt-1 italic">${work.journal_title}</p>` : ''}
                    <div class="mt-3 flex flex-wrap items-center gap-2">
                        <span class="text-[10px] uppercase font-bold text-slate-400 bg-slate-50 px-2 py-0.5 rounded border border-slate-100">${work.type.replace(/-/g, ' ')}</span>
                        ${work.publication_year ? `<span class="text-xs font-bold text-slate-600">${work.publication_year}</span>` : ''}
                        <div class="flex flex-wrap gap-2 ml-auto">${idsHtml}</div>
                    </div>
                </div>
            `);
        });
    }
}