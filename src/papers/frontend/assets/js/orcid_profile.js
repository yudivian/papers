$(document).ready(function () {

    setTimeout(() => {
        if (typeof restoreTasks === 'function') restoreTasks();
    }, 500);

    $('#btnOpenSettingsFromError').on('click', function () {
        $('#settingsBtn').trigger('click');
    });

    $('#btnSyncProfile, #btnSyncNowBanner').on('click', function() {
        syncProfile();
    });

    loadLocalProfile();
});

async function loadLocalProfile() {
    $('#orcid-loading').removeClass('hidden');
    $('#orcid-content').addClass('hidden');
    $('#orcid-error').addClass('hidden');
    
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
            checkFreshness(profile.last_updated);
        },
        error: function (err) {
            $('#orcid-loading').addClass('hidden');
            if (err.status === 404) {
                syncProfile(); 
            } else {
                $('#orcid-error').removeClass('hidden').addClass('flex');
                $('#orcid-error-text').text("ORCID integration is disabled or not configured properly.");
            }
        }
    });
}

async function syncProfile() {
    const btn = $('#btnSyncProfile');
    const icon = $('#syncIcon');
    btn.prop('disabled', true).addClass('opacity-50');
    icon.addClass('animate-spin');
    
    $.ajax({
        url: '/api/v1/orcid/sync',
        type: 'POST',
        success: function (profile) {
            $('#orcid-loading').addClass('hidden');
            $('#orcid-content').removeClass('hidden');
            $('#orcid-error').addClass('hidden');
            
            renderHeader(profile);
            renderBioAndKeywords(profile);
            renderLinks(profile);
            renderAffiliations(profile);
            renderWorks(profile);
            
            $('#sync-banner').addClass('hidden');
            if (window.showToast) window.showToast('Profile updated from ORCID.', 'success');
        },
        error: function () {
            if (window.showToast) window.showToast('Sync failed. Try again later.', 'error');
            $('#orcid-loading').addClass('hidden');
            $('#orcid-error').removeClass('hidden').addClass('flex');
            $('#orcid-error-text').text("Failed to reach ORCID API.");
        },
        complete: function () {
            btn.prop('disabled', false).removeClass('opacity-50');
            icon.removeClass('animate-spin');
        }
    });
}

function checkFreshness(lastUpdatedStr) {
    if (!lastUpdatedStr) return;
    const lastSync = new Date(lastUpdatedStr);
    const now = new Date();
    const diffDays = Math.ceil((now - lastSync) / (1000 * 60 * 60 * 24));
    if (diffDays > 7) $('#sync-banner').removeClass('hidden');
}

function renderHeader(profile) {
    $('#prof-name').text(profile.full_name);
    $('#prof-orcid-link').text(profile.orcid_id).attr('href', `https://orcid.org/${profile.orcid_id}`);
    if (profile.last_updated) {
        $('#last-sync-time').text(new Date(profile.last_updated).toLocaleString());
    }
}

function renderBioAndKeywords(profile) {
    if (profile.biography) {
        $('#prof-bio-section').removeClass('hidden');
        $('#prof-bio').text(profile.biography);
    } else {
        $('#prof-bio-section').addClass('hidden');
    }
    
    if (profile.keywords && profile.keywords.length > 0) {
        $('#prof-keywords-section').removeClass('hidden');
        const kwContainer = $('#prof-keywords').empty();
        profile.keywords.forEach(kw => {
            kwContainer.append(`<span class="px-2.5 py-1 bg-slate-100 border border-slate-200 text-slate-600 rounded-md text-xs font-medium">${kw}</span>`);
        });
    } else {
        $('#prof-keywords-section').addClass('hidden');
    }
}

function renderLinks(profile) {
    if (profile.researcher_urls && profile.researcher_urls.length > 0) {
        $('#prof-links-section').removeClass('hidden');
        const ul = $('#prof-links').empty();
        profile.researcher_urls.forEach(link => {
            const nameStr = link.name || link.url;
            ul.append(`<li><a href="${link.url}" target="_blank" class="text-blue-600 hover:underline flex items-center gap-1"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path></svg>${nameStr}</a></li>`);
        });
    } else {
        $('#prof-links-section').addClass('hidden');
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
            const badgeClass = aff.type === 'Employment' ? 'bg-blue-50 text-blue-600' : 'bg-purple-50 text-purple-600';
            container.append(`
                <div class="bg-white p-4 rounded-lg border border-slate-200 flex justify-between items-center shadow-sm">
                    <div>
                        <h4 class="font-bold text-slate-800 text-sm">${aff.role}</h4>
                        <p class="text-xs text-slate-500">${aff.organization}</p>
                    </div>
                    <div class="text-right flex flex-col items-end">
                        <span class="text-[10px] uppercase font-bold px-2 py-0.5 rounded-full ${badgeClass}">${aff.type}</span>
                        <p class="text-[10px] text-slate-400 mt-1 font-mono">${dateStr}</p>
                    </div>
                </div>
            `);
        });
    } else {
        $('#prof-affiliations-section').addClass('hidden');
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
                    if (ext.type.toLowerCase() === 'doi') {
                        const url = ext.url || `https://doi.org/${ext.value}`;
                        idsHtml += `<a href="${url}" target="_blank" class="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-indigo-50 border border-indigo-100 text-indigo-700 text-xs font-mono hover:bg-indigo-100 transition-colors">DOI: ${ext.value}</a>`;
                    } else {
                        idsHtml += `<span class="inline-flex items-center px-2 py-0.5 rounded bg-slate-50 border border-slate-200 text-slate-500 text-xs font-mono">${ext.type.toUpperCase()}: ${ext.value}</span>`;
                    }
                });
            }

            container.append(`
                <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm hover:border-indigo-300 transition-colors group">
                    <h3 class="font-bold text-slate-900 group-hover:text-indigo-700 leading-snug">${work.title}</h3>
                    ${work.journal_title ? `<p class="text-xs text-slate-500 mt-1 italic">${work.journal_title}</p>` : ''}
                    <div class="mt-3 flex flex-wrap items-center gap-2">
                        <span class="text-[10px] uppercase font-bold text-slate-400 bg-slate-50 px-2 py-0.5 rounded border border-slate-100">${work.type.replace(/-/g, ' ')}</span>
                        ${work.publication_year ? `<span class="text-xs font-bold text-slate-600">${work.publication_year}</span>` : ''}
                        <div class="flex flex-wrap gap-2 ml-auto">${idsHtml}</div>
                    </div>
                </div>
            `);
        });
    } else {
        $('#prof-works-section').addClass('hidden');
    }
}