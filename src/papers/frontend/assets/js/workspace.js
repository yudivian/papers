/**
 * Workspace Controller
 * Handles the display, creation, and deletion of Knowledge Bases.
 */

let confirmActionCallback = null;
let currentDocumentsData = []; // Guarda los documentos de la KB abierta
let currentKBsData = [];       // Guarda KBs para poder filtrarlas
let currentRenderedKBId = null; // Guarda el ID de la KB actual

function formatDate(isoString) {
    if (!isoString) return 'No date';
    const date = new Date(isoString);
    return date.toLocaleDateString('es-ES', { 
        day: 'numeric', 
        month: 'short', 
        year: 'numeric' 
    });
}

$(document).ready(function () {
    if ($('#component-registry').length === 0) {
        $('body').append('<div id="component-registry" class="hidden"></div>');
        const cacheBuster = '?v=' + new Date().getTime();
        $('#component-registry').load('/components/doi_card.html' + cacheBuster, function() {
             console.log("Templates loaded successfully (Cache Busted!)");
        });
    }
    loadKBs();

    $('#btnNewKB').on('click', openModal);
    $('#btnCloseModal, #btnCancelModal').on('click', closeModal);

    $('#btnCreateStay').on('click', function (e) {
        if ($('#formNewKB')[0].checkValidity()) {
            e.preventDefault();
            createKB(false);
        } else {
            $('#formNewKB')[0].reportValidity();
        }
    });

    $('#formNewKB').on('submit', function (e) {
        e.preventDefault(); 
        createKB(true); 
    });

    $('#btnBackToGrid').on('click', showGrid);

    $('#btnCancelConfirm').on('click', closeConfirmModal);
    $('#btnAcceptConfirm').on('click', function () {
        if (confirmActionCallback) confirmActionCallback();
        closeConfirmModal();
    });


    $('#btnCloseEditModal, #btnCancelEditModal').on('click', closeEditModal);
    $('#formEditKB').on('submit', function (e) {
        e.preventDefault();
        executeEdit();
    });
    
});

function loadKBs() {
    const grid = $('#workspace-grid');
    const $sortBar = $('#kb-toolbar'); // O kb-sort-bar según tu HTML
    
    if ($('#workspace-detail').hasClass('hidden')) {
        grid.html('<p class="text-slate-500 col-span-full text-center py-10">Loading knowledge bases...</p>');
    }

    $.get('/kbs').done(function (kbs) {
        currentKBsData = kbs || [];
        renderSortedKBs();
    }).fail(function () {
        if ($('#workspace-detail').hasClass('hidden')) {
            $sortBar.addClass('hidden');
            grid.html('<div class="col-span-full p-8 text-center bg-red-50 border border-red-100 rounded-xl text-red-600">Error loading projects. Check if the backend is running.</div>');
        }
    });
}

function createKB(enterAfterCreation) {
    const name = $('#kbName').val().trim();
    const desc = $('#kbDesc').val().trim();

    $.ajax({
        url: '/kbs',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ name: name, description: desc }),
        success: function (response) {
            closeModal();
            if(window.showToast) window.showToast(`Project "${name}" created.`, 'success');

            if (enterAfterCreation) {
                const newId = response.kb_id || response.id || name;
                $.get(`/kbs/${newId}`).done(function(fullKb) {
                    showDetail(fullKb); 
                    loadKBs();         
                }).fail(function() {
                    loadKBs(); 
                });
            } else {
                loadKBs();
            }
        },
        error: function (err) {
            if(window.showToast) window.showToast('Error creating project.', 'error');
            console.error(err);
        }
    });
}

function requestDeleteKB(kb) {
    const targetId = kb.id || kb.kb_id || kb.name;

    if (!targetId) {
        if(window.showToast) window.showToast('Error: Could not identify the Knowledge Base ID.', 'error');
        return;
    }

    if (currentKBsData && currentKBsData.length <= 1) {
        if(window.showToast) window.showToast('You cannot delete your last Knowledge Base. At least one must remain.', 'error');
        return; 
    }

    openConfirmModal(
        'Delete Knowledge Base',
        `Are you sure you want to delete the project <br><b class="text-slate-800">"${kb.name}"</b>?<br><br>Documents inside will remain safely on your disk.`,
        function () {
            executeDelete(targetId);
        }
    );
}

function executeDelete(kbId) {
    $.ajax({
        url: `/kbs/${kbId}`,
        type: 'DELETE',
        success: function () {
            if(window.showToast) window.showToast('Project deleted successfully.', 'success');      
            $('#workspace-detail').addClass('hidden');    
            showGrid(); 
        },
        error: function (err) {
            if(window.showToast) window.showToast('Failed to delete project.', 'error');
            console.error(err);
        }
    });
}

function showGrid() {
    $('#workspace-detail').addClass('hidden');
    $('#workspace-grid').removeClass('hidden');
    // Asegurar que la barra de herramientas se muestre
    $('#kb-toolbar').removeClass('hidden'); 
    $('#kb-sort-bar').removeClass('hidden'); 
    loadKBs();
}

function openModal() {
    $('#kbName').val('');
    $('#kbDesc').val('');
    $('#modalNewKB').removeClass('hidden');
    setTimeout(() => { $('#modalNewKB > div').removeClass('scale-95').addClass('scale-100'); }, 10);
}

function closeModal() {
    $('#modalNewKB > div').removeClass('scale-100').addClass('scale-95');
    setTimeout(() => { $('#modalNewKB').addClass('hidden'); }, 150);
}

function openConfirmModal(title, message, onConfirm) {
    $('#confirmTitle').text(title);
    $('#confirmMessage').html(message);
    confirmActionCallback = onConfirm;

    $('#modalConfirm').removeClass('hidden');
    setTimeout(() => { $('#modalConfirm > div').removeClass('scale-95').addClass('scale-100'); }, 10);
}

function closeConfirmModal() {
    $('#modalConfirm > div').removeClass('scale-100').addClass('scale-95');
    setTimeout(() => {
        $('#modalConfirm').addClass('hidden');
        confirmActionCallback = null;
    }, 150);
}

function openEditModal(kb) {
    if (!kb) return;
    $('#editKbId').val(kb.id || kb.kb_id || kb.name);
    $('#editKbName').val(kb.name);
    $('#editKbDesc').val(kb.description || '');

    $('#modalEditKB').removeClass('hidden');
    setTimeout(() => {
        $('#modalEditKB > div').removeClass('scale-95').addClass('scale-100');
    }, 10);
}

function closeEditModal() {
    $('#modalEditKB > div').removeClass('scale-100').addClass('scale-95');
    setTimeout(() => { $('#modalEditKB').addClass('hidden'); }, 150);
}

function executeEdit() {
    const kbId = $('#editKbId').val();
    const newName = $('#editKbName').val().trim();
    const newDesc = $('#editKbDesc').val().trim();

    if (!newName) {
        if (window.showToast) window.showToast('Project name is required.', 'error');
        return;
    }

    $.ajax({
        url: `/kbs/${kbId}`,
        type: 'PATCH',
        contentType: 'application/json',
        data: JSON.stringify({ name: newName, description: newDesc }),
        success: function (updatedKb) {
            closeEditModal();
            if (window.showToast) window.showToast('Project updated successfully.', 'success');

            if (!$('#workspace-detail').hasClass('hidden')) {
                $('#detailTitle').text(updatedKb.name);
                $('#detailDesc').text(updatedKb.description || 'No description provided.');
                $('#btnEditKB').off('click').on('click', () => openEditModal(updatedKb));
                $('#btnDeleteKB').off('click').on('click', () => requestDeleteKB(updatedKb));
                
                const index = currentKBsData.findIndex(k => (k.kb_id || k.id) === updatedKb.kb_id);
                if(index !== -1) currentKBsData[index] = updatedKb;
            } else {
                loadKBs(); 
            }
        },
        error: function (err) {
            if (window.showToast) window.showToast('Failed to update project. Check backend logs.', 'error');
        }
    });
}

function loadKBDetail(kbId) {
    window.currentKBId = kbId;
    $.get(`/kbs/${kbId}`).done(function (fullKb) {
        showDetail(fullKb); 
    }).fail(function () {
        if (window.showToast) window.showToast('Error loading project details.', 'error');
    });
}

function showDetail(kb) {
    $('#workspace-grid').addClass('hidden');
    $('#kb-toolbar').addClass('hidden'); 
    $('#kb-sort-bar').addClass('hidden'); 
    $('#workspace-detail').removeClass('hidden');

    $('#detailTitle').text(kb.name);
    $('#detailDesc').text(kb.description || 'Sin descripción.');
    $('#detailDate').html(`
        <svg class="w-3 h-3 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
        Creado: ${formatDate(kb.created_at)}
    `);

    $('#btnEditKB').off('click').on('click', () => openEditModal(kb));
    $('#btnDeleteKB').off('click').on('click', () => requestDeleteKB(kb));

    currentDocumentsData = kb.documents || [];
    currentRenderedKBId = kb.kb_id || kb.id;
    
    // Oculta/Muestra el header de documentos
    if (currentDocumentsData.length < 2) {
        $('#doc-header-container').addClass('hidden');
    } else {
        $('#doc-header-container').removeClass('hidden');
    }

    renderSortedDocuments();
}

function renderKBDocument(doc, kbId) {
    const $tpl = $('#tpl-kb-document-item').prop('content');
    const $item = $(document.importNode($tpl, true));
    const $card = $item.find('.js-doc-card');

    $card.attr('data-doi', doc.doi);

    $item.find('.js-doc-title').text(doc.title || 'Untitled Document');
    $item.find('.js-doc-authors').text(doc.authors && doc.authors.length > 0 ? doc.authors.join(', ') : 'Unknown Authors');
    $item.find('.js-doc-abstract').text(doc.abstract || 'No abstract available.');

    if (doc.type) $item.find('.js-doc-type').text(doc.type).removeClass('hidden');
    if (doc.year) $item.find('.js-doc-year').text(doc.year).removeClass('hidden');
    if (doc.file_size) $item.find('.js-doc-size').text(formatBytes(doc.file_size)).removeClass('hidden');
    if (doc.doi) {
        const doiLink = doc.doi.startsWith('http') ? doc.doi : `https://doi.org/${doc.doi}`;
        $item.find('.js-doc-doi').text(doc.doi).attr('href', doiLink).removeClass('hidden');
    }

    if (doc.venue || doc.publisher) {
        $item.find('.js-doc-venue').text(doc.venue || doc.publisher);
        $item.find('.js-doc-venue-container').removeClass('hidden');
    }
    if (doc.ingested_at) {
        const date = new Date(doc.ingested_at).toLocaleDateString();
        $item.find('.js-doc-added').text(date);
        $item.find('.js-doc-added-container').removeClass('hidden');
    }

    if (doc.keywords && doc.keywords.length > 0) { 
        const $topicsContainer = $item.find('.js-doc-topics');
        doc.keywords.forEach(keyword => {
            $topicsContainer.append(
                `<span class="px-2 py-1 bg-slate-100 border border-slate-200 text-slate-600 rounded text-[10px] uppercase font-bold tracking-wider">${keyword}</span>`
            );
        });
        $item.find('.js-doc-topics-container').removeClass('hidden');
    }

    $item.find('.js-btn-toggle-meta').on('click', function () {
        $card.find('.js-doc-meta-panel').slideToggle(250);
    });

    $item.find('.js-btn-download-doc').on('click', function(e) {
        e.stopPropagation();
        const url = `/documents/${encodeURIComponent(doc.doi)}/file`;
        
        $.ajax({
            url: url,
            type: 'GET',
            xhrFields: { responseType: 'blob' },
            success: function(blob, status, xhr) {
                let filename = `${doc.title || 'document'}.pdf`; 
                const disposition = xhr.getResponseHeader('Content-Disposition');
                if (disposition && disposition.indexOf('attachment') !== -1) {
                    const matches = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/.exec(disposition);
                    if (matches != null && matches[1]) filename = matches[1].replace(/['"]/g, '');
                }
                const blobUrl = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.style.display = 'none';
                a.href = blobUrl;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(blobUrl);
                document.body.removeChild(a);
            },
            error: function() {
                if (window.showToast) window.showToast('Error downloading file.', 'error');
            }
        });
    });

    $item.find('.js-btn-unlink-doc').on('click', function () {
        openConfirmModal('Remove Document', `Unlink "${doc.title}"?`, function () {
            $.ajax({
                url: `/kbs/${kbId}/documents/${encodeURIComponent(doc.doi)}`,
                type: 'DELETE',
                success: function () {
                    $card.fadeOut(300, () => $card.remove());
                    // Quitarlo de la memoria principal
                    currentDocumentsData = currentDocumentsData.filter(d => d.doi !== doc.doi);
                    if (window.showToast) window.showToast('Document removed', 'success');
                }
            });
        });
    });

    $item.find('.js-btn-move-doc').on('click', () => openTransferModal('transfer', doc.doi, kbId));
    $item.find('.js-btn-copy-doc').on('click', () => openTransferModal('copy', doc.doi, kbId));

    $('#kb-documents-container').append($item);
}

function openTransferModal(actionType, doi, sourceKbId) {
    if ($('#modal-kb-select').length === 0) {
        const $tpl = $('#tpl-kb-modal').prop('content');
        $('body').append(document.importNode($tpl, true));
        $('#btn-modal-cancel').on('click', function() {
            $('#modal-kb-select').addClass('hidden');
        });
    }

    const $dropdown = $('#modal-kb-dropdown').empty();
    $dropdown.append('<option value="" disabled selected>Select a Knowledge Base...</option>');
    
    $.get('/kbs').done(function(kbs) {
        kbs.forEach(kb => {
            const id = kb.kb_id || kb.id;
            if (id !== sourceKbId) {
                $dropdown.append(`<option value="${id}">${kb.name}</option>`);
            }
        });
    });

    $('#btn-modal-download').prop('disabled', true).text(actionType === 'copy' ? 'Copy Document' : 'Move Document');
    $dropdown.off('change').on('change', function() {
        $('#btn-modal-download').prop('disabled', false);
    });

    $('#modal-kb-select').removeClass('hidden');

    $('#btn-modal-download').off('click').on('click', function () {
        const targetKbId = $('#modal-kb-dropdown').val();
        if (!targetKbId) return;

        $.ajax({
            url: `/kbs/${targetKbId}/${actionType}`,
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                dois: [doi],
                source_kb_id: sourceKbId
            }),
            success: function () {
                $('#modal-kb-select').addClass('hidden');
                
                if (actionType === 'transfer') {
                    $(`[data-doi="${doi}"]`).fadeOut(300, function() { $(this).remove(); });
                    currentDocumentsData = currentDocumentsData.filter(d => d.doi !== doi);
                }
                if (window.showToast) window.showToast(`Document ${actionType}ed successfully`, 'success');
            }
        });
    });
}

function formatBytes(bytes, decimals = 1) {
    if (!+bytes) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
}


// =========================================================================
// MOTORES DE RENDERIZADO Y ORDENAMIENTO DE KBs y DOCS
// =========================================================================

function renderSortedKBs() {
    const grid = $('#workspace-grid').empty();
    const $toolbar = $('#kb-toolbar'); // O #kb-sort-bar
    
    if ($('#workspace-detail').hasClass('hidden')) {
        grid.removeClass('hidden');
    }

    if (!currentKBsData || currentKBsData.length === 0) {
        $toolbar.addClass('hidden');
        grid.html(`
            <div class="col-span-full bg-white border border-slate-200 border-dashed rounded-xl p-12 text-center">
                <p class="text-slate-500 mb-4">You don't have any Knowledge Bases yet.</p>
                <button onclick="openModal()" class="text-blue-600 font-medium hover:underline">Create your first project</button>
            </div>
        `);
        return;
    }

    // Filtrado de Buscador para KBs
    const searchTerm = ($('#kb-search-input').val() || '').toLowerCase();
    let filteredKBs = currentKBsData;

    if (searchTerm) {
        filteredKBs = currentKBsData.filter(kb => 
            (kb.name || '').toLowerCase().includes(searchTerm) || 
            (kb.description || '').toLowerCase().includes(searchTerm)
        );
    }

    if (currentKBsData.length <= 1) {
        $toolbar.addClass('hidden');
    } else {
        if ($('#workspace-detail').hasClass('hidden')) {
            $toolbar.removeClass('hidden');
        }
    }

    if (filteredKBs.length === 0) {
        grid.html(`
            <div class="col-span-full p-8 text-center bg-slate-50 border border-dashed border-slate-200 rounded-xl mt-4">
                <p class="text-slate-500">No Knowledge Bases found matching "<b>${searchTerm}</b>".</p>
                <button onclick="$('#kb-search-input').val('').trigger('input');" class="mt-2 text-sm text-blue-600 hover:underline">Clear search</button>
            </div>
        `);
        return;
    }

    // Auto-setup de botones KBs
    let $activeBtn = $('.kb-sort-btn.text-blue-600');
    if ($activeBtn.length === 0) {
        $activeBtn = $('.kb-sort-btn[data-sort="created_at"]');
        if ($activeBtn.length === 0) $activeBtn = $('.kb-sort-btn').first();
        $activeBtn.attr('data-dir', 'desc').addClass('font-bold text-blue-600').removeClass('font-medium text-slate-500');
    }

    $('.kb-sort-btn').each(function() {
        const $b = $(this);
        let dir = $b.attr('data-dir');
        if (!dir || dir === 'none') {
            dir = ($b.data('sort') === 'name') ? 'asc' : 'desc';
            $b.attr('data-dir', dir);
        }
        const isThisActive = $b.hasClass('text-blue-600');
        $b.find('.sort-icon').text(dir === 'asc' ? '↑' : '↓').toggleClass('opacity-50', !isThisActive);
    });

    const sortField = $activeBtn.data('sort') || 'created_at';
    const sortDir = $activeBtn.attr('data-dir') || 'desc';

    let kbsToSort = filteredKBs.slice();

    kbsToSort.sort((a, b) => {
        let valA, valB;
        if (sortField === 'name') {
            valA = (a.name || '').toLowerCase();
            valB = (b.name || '').toLowerCase();
        } else if (sortField === 'docs') {
            // ¡AQUÍ ESTÁ LA MAGIA! Tu variable original document_ids
            valA = a.document_ids ? a.document_ids.length : 0;
            valB = b.document_ids ? b.document_ids.length : 0;
        } else if (sortField === 'created_at') {
            valA = new Date(a.created_at || 0).getTime();
            valB = new Date(b.created_at || 0).getTime();
        }

        if (valA < valB) return sortDir === 'asc' ? -1 : 1;
        if (valA > valB) return sortDir === 'asc' ? 1 : -1;
        
        let tieA = (a.name || '').toLowerCase(); 
        let tieB = (b.name || '').toLowerCase();
        if (tieA < tieB) return sortDir === 'asc' ? -1 : 1;
        if (tieA > tieB) return sortDir === 'asc' ? 1 : -1;
        return 0;
    });

    // Renderizado del HTML exacto de tu repo
    kbsToSort.forEach(kb => {
        // Tu conteo original
        const docCount = kb.document_ids ? kb.document_ids.length : 0;
        const displayDate = formatDate(kb.created_at);

        const card = $(`
            <div class="relative bg-white border border-slate-200 rounded-xl p-6 hover:shadow-md hover:border-blue-300 transition-all cursor-pointer group flex flex-col h-full">
                <div class="absolute top-3 right-3 flex gap-1 opacity-0 group-hover:opacity-100 transition-all">
                    <button class="btn-edit-card text-slate-400 hover:text-blue-600 p-2 rounded-lg" title="Editar">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                    </button>
                    <button class="btn-delete-card text-slate-400 hover:text-red-500 p-2 rounded-lg" title="Eliminar">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                    </button>
                </div>
                
                <div class="flex-1 pr-14">
                    <h3 class="text-lg font-bold text-slate-800 group-hover:text-blue-600 transition-colors line-clamp-1">${kb.name}</h3>
                    <p class="text-sm text-slate-500 mt-2 line-clamp-2">${kb.description || 'Sin descripción.'}</p>
                    <p class="text-[10px] font-bold text-slate-400 uppercase mt-4 tracking-wider flex items-center">
                        <svg class="w-3 h-3 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                        Created: ${displayDate}
                    </p>
                </div>
                
                <div class="mt-6 pt-4 border-t border-slate-50 flex justify-between items-center">
                    <span class="text-xs font-semibold px-2 py-1 bg-blue-50 text-blue-700 rounded-md">
                        ${docCount} Documentos
                    </span>
                    <span class="text-slate-400 text-lg opacity-0 group-hover:opacity-100 transition-opacity">→</span>
                </div>
            </div>
        `);

        card.on('click', () => loadKBDetail(kb.kb_id || kb.id));
        card.find('.btn-edit-card').on('click', (e) => { e.stopPropagation(); openEditModal(kb); });
        card.find('.btn-delete-card').on('click', (e) => { e.stopPropagation(); requestDeleteKB(kb); });

        grid.append(card);
    });
}

function renderSortedDocuments() {
    const $container = $('#kb-documents-container').empty();
    const $headerContainer = $('#doc-header-container'); // Referencia a la barra
    
    // REGLA DE UX: Ocultar barra si hay menos de 2 documentos
    if (currentDocumentsData.length < 2) {
        $headerContainer.addClass('hidden');
    } else {
        $headerContainer.removeClass('hidden');
    }

    // Filtrado local para documentos
    const searchTerm = ($('#doc-search-input').val() || '').toLowerCase();
    let filteredDocs = currentDocumentsData;

    if (searchTerm) {
        filteredDocs = currentDocumentsData.filter(doc => 
            (doc.title || '').toLowerCase().includes(searchTerm) || 
            (doc.abstract || '').toLowerCase().includes(searchTerm) ||
            ((doc.authors || []).join(' ')).toLowerCase().includes(searchTerm)
        );
    }

    if (currentDocumentsData.length === 0) {
        $container.append('<p class="text-slate-400 text-sm italic p-4">Esta biblioteca está vacía.</p>');
        return;
    }

    if (filteredDocs.length === 0) {
        $container.append(`
            <div class="p-8 text-center bg-slate-50 border border-dashed border-slate-200 rounded-xl mt-4">
                <p class="text-slate-500">No documents found matching "<b>${searchTerm}</b>".</p>
                <button onclick="$('#doc-search-input').val('').trigger('input');" class="mt-2 text-sm text-blue-600 hover:underline">Clear search</button>
            </div>
        `);
        return;
    }

    // Auto-setup de botones
    let $activeBtn = $('.doc-sort-btn.text-blue-600');
    if ($activeBtn.length === 0) {
        $activeBtn = $('.doc-sort-btn[data-sort="ingested_at"]');
        if ($activeBtn.length === 0) $activeBtn = $('.doc-sort-btn').first();
        $activeBtn.attr('data-dir', 'desc').addClass('font-bold text-blue-600').removeClass('font-medium text-slate-500 hover:text-slate-800');
    }

    $('.doc-sort-btn').each(function() {
        const $b = $(this);
        let dir = $b.attr('data-dir');
        if (!dir || dir === 'none') {
            dir = ($b.data('sort') === 'title') ? 'asc' : 'desc';
            $b.attr('data-dir', dir);
        }
        const isThisActive = $b.hasClass('text-blue-600');
        $b.find('.sort-icon').text(dir === 'asc' ? '↑' : '↓').toggleClass('opacity-50', !isThisActive);
    });

    const sortField = $activeBtn.data('sort') || 'ingested_at';
    const sortDir = $activeBtn.attr('data-dir') || 'desc';

    let docsToSort = filteredDocs.slice();

    docsToSort.sort((a, b) => {
        let valA, valB;
        if (sortField === 'title') {
            valA = (a.title || '').toLowerCase();
            valB = (b.title || '').toLowerCase();
        } else if (sortField === 'file_size') {
            valA = a.file_size || 0;
            valB = b.file_size || 0;
        } else if (sortField === 'year') {
            valA = a.year || 0;
            valB = b.year || 0;
        } else if (sortField === 'ingested_at') {
            valA = new Date(a.ingested_at || 0).getTime();
            valB = new Date(b.ingested_at || 0).getTime();
        }

        if (valA < valB) return sortDir === 'asc' ? -1 : 1;
        if (valA > valB) return sortDir === 'asc' ? 1 : -1;
        
        let tieA = (a.title || a.doi || '').toLowerCase(); 
        let tieB = (b.title || b.doi || '').toLowerCase();
        if (tieA < tieB) return sortDir === 'asc' ? -1 : 1;
        if (tieA > tieB) return sortDir === 'asc' ? 1 : -1;
        return 0;
    });

    docsToSort.forEach(doc => {
        renderKBDocument(doc, currentRenderedKBId);
    });
}

// =========================================================================
// ESCUCHADORES DE EVENTOS PARA EL 1-CLICK Y BUSCADOR
// =========================================================================

// Para KBs
$(document).off('click', '.kb-sort-btn').on('click', '.kb-sort-btn', function(e) {
    e.preventDefault();
    const $btn = $(this);
    const isActive = $btn.hasClass('text-blue-600'); 
    const currentDir = $btn.attr('data-dir');
    const nextDir = isActive ? (currentDir === 'asc' ? 'desc' : 'asc') : currentDir;

    $('.kb-sort-btn').removeClass('font-bold text-blue-600').addClass('font-medium text-slate-500');
    $btn.attr('data-dir', nextDir).removeClass('font-medium text-slate-500').addClass('font-bold text-blue-600');
    
    renderSortedKBs();
});

$(document).off('input', '#kb-search-input').on('input', '#kb-search-input', function() {
    renderSortedKBs();
});

// Para Documentos
$(document).off('click', '.doc-sort-btn').on('click', '.doc-sort-btn', function(e) {
    e.preventDefault();
    const $btn = $(this);
    const isActive = $btn.hasClass('text-blue-600'); 
    const currentDir = $btn.attr('data-dir');
    const nextDir = isActive ? (currentDir === 'asc' ? 'desc' : 'asc') : currentDir;

    $('.doc-sort-btn').removeClass('font-bold text-blue-600').addClass('font-medium text-slate-500 hover:text-slate-800');
    $btn.attr('data-dir', nextDir).removeClass('font-medium text-slate-500 hover:text-slate-800').addClass('font-bold text-blue-600');
    
    renderSortedDocuments();
});

$(document).off('input', '#doc-search-input').on('input', '#doc-search-input', function() {
    renderSortedDocuments();
});