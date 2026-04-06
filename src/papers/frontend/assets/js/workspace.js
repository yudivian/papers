/**
 * Workspace Controller
 * Handles the display, creation, and deletion of Knowledge Bases.
 */

let confirmActionCallback = null;
let currentDocumentsData = []; // Guarda los documentos de la KB abierta
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
    // 1. Initial Load
    // 1. Initial Load
    if ($('#component-registry').length === 0) {
        $('body').append('<div id="component-registry" class="hidden"></div>');
        
        // TRUCO ANTI-CACHÉ: Le añadimos la hora exacta a la URL para que el navegador 
        // crea que es un archivo nuevo y se vea obligado a descargarlo de tu disco.
        const cacheBuster = '?v=' + new Date().getTime();
        
        $('#component-registry').load('/components/doi_card.html' + cacheBuster, function() {
             console.log("Templates loaded successfully (Cache Busted!)");
        });
    }
    loadKBs();

    // 2. KB Modal interactions
    $('#btnNewKB').on('click', openModal);
    $('#btnCloseModal, #btnCancelModal').on('click', closeModal);

    // 3. Form submission
    // 3. Form submission and Create buttons
    $('#btnCreateStay').on('click', function (e) {
        if ($('#formNewKB')[0].checkValidity()) {
            e.preventDefault();
            createKB(false); // false = no entrar
        } else {
            $('#formNewKB')[0].reportValidity();
        }
    });

    $('#formNewKB').on('submit', function (e) {
        e.preventDefault(); // El botón "Create & Enter" (type=submit) activa esto
        createKB(true); // true = entrar automáticamente
    });

    // 4. View switching
    $('#btnBackToGrid').on('click', showGrid);

    // 5. Confirm Modal bindings
    $('#btnCancelConfirm').on('click', closeConfirmModal);
    $('#btnAcceptConfirm').on('click', function () {
        if (confirmActionCallback) confirmActionCallback();
        closeConfirmModal();
    });

    // Mobile Sidebar toggle
    $(document).on('click', '#openSidebarMobileBtn', function () {
        $('#mobileSidebarOverlay').removeClass('hidden');
        setTimeout(() => {
            $('#mobileSidebarOverlay').removeClass('opacity-0').addClass('opacity-100');
            $('#mainSidebar').removeClass('-translate-x-full');
        }, 10);
    });

    // (Debajo de los listeners que ya tienes)
    $('#btnCloseEditModal, #btnCancelEditModal').on('click', closeEditModal);
    $('#formEditKB').on('submit', function (e) {
        e.preventDefault();
        executeEdit();
    });
});

function loadKBs() {
    const grid = $('#workspace-grid');
    const $sortBar = $('#kb-sort-bar');
    
    // Solo mostramos el mensaje de "Loading..." si estamos en la pantalla principal
    if ($('#workspace-detail').hasClass('hidden')) {
        grid.html('<p class="text-slate-500 col-span-full text-center py-10">Loading knowledge bases...</p>');
    }

    $.get('/kbs').done(function (kbs) {
        currentKBsData = kbs;
        
        // ELIMINADA la lógica rebelde que encendía la barra por error.
        // Ahora delegamos todo el control visual a renderSortedKBs.
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
            window.showToast(`Project "${name}" created.`, 'success');

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
            window.showToast('Error creating project.', 'error');
            console.error(err);
        }
    });
}

function requestDeleteKB(kb) {
    const targetId = kb.id || kb.kb_id || kb.name;

    if (!targetId) {
        window.showToast('Error: Could not identify the Knowledge Base ID.', 'error');
        return;
    }

    if (currentKBsData && currentKBsData.length <= 1) {
        window.showToast('You cannot delete your last Knowledge Base. At least one must remain.', 'error');
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
            window.showToast('Project deleted successfully.', 'success');      
            $('#workspace-detail').addClass('hidden');    
            showGrid(); 
        },
        error: function (err) {
            window.showToast('Failed to delete project.', 'error');
            console.error(err);
        }
    });
}






function showGrid() {
    // Ocultar detalle
    $('#workspace-detail').addClass('hidden');
    
    // Volver a mostrar TODO lo del workspace
    $('#workspace-grid').removeClass('hidden');
    $('#kb-sort-bar').removeClass('hidden'); 
    
    loadKBs();
}

// --- Modals Logic ---

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

// --- Edit Logic ---

function openEditModal(kb) {
    if (!kb) return;

    // Llenar el formulario
    $('#editKbId').val(kb.id || kb.kb_id || kb.name);
    $('#editKbName').val(kb.name);
    $('#editKbDesc').val(kb.description || '');

    // Quitamos el '.css('display', 'flex')' que causaba el bug. 
    // Solo removemos la clase hidden.
    $('#modalEditKB').removeClass('hidden');

    // Animación de entrada
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

            // Si estamos dentro del detalle, actualizamos los textos pero NO recargamos el grid
            if (!$('#workspace-detail').hasClass('hidden')) {
                $('#detailTitle').text(updatedKb.name);
                $('#detailDesc').text(updatedKb.description || 'No description provided.');
                $('#btnEditKB').off('click').on('click', () => openEditModal(updatedKb));
                $('#btnDeleteKB').off('click').on('click', () => requestDeleteKB(updatedKb));
                
                // Actualizamos la memoria silenciosamente
                const index = currentKBsData.findIndex(k => (k.kb_id || k.id) === updatedKb.kb_id);
                if(index !== -1) currentKBsData[index] = updatedKb;
            } else {
                // Solo recargamos el grid si estábamos en la pantalla principal
                loadKBs(); 
            }
        },
        error: function (err) {
            if (window.showToast) window.showToast('Failed to update project. Check backend logs.', 'error');
            console.error("Error updating KB:", err);
        }
    });
}


function loadKBDetail(kbId) {
    window.currentKBId = kbId;
    
    // Volvemos a hacer la petición real al backend
    $.get(`/kbs/${kbId}`).done(function (fullKb) {
        showDetail(fullKb); // Le pasamos los datos completos (con documentos) a showDetail
    }).fail(function () {
        if (window.showToast) window.showToast('Error loading project details.', 'error');
    });
}

function showDetail(kb) {
    // 1. Navegación (Ocultar Grid, Mostrar Detalle)
    $('#workspace-grid').addClass('hidden');
    $('#kb-sort-bar').addClass('hidden'); 
    $('#workspace-detail').removeClass('hidden');
    $('#doc-search-input').val('');

    // 2. Pintar Textos de la KB
    $('#detailTitle').text(kb.name);
    $('#detailDesc').text(kb.description || 'Sin descripción.');
    $('#detailDate').html(`
        <svg class="w-3 h-3 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
        Creado: ${formatDate(kb.created_at)}
    `);

    // 3. Eventos de la KB
    $('#btnEditKB').off('click').on('click', () => openEditModal(kb));
    $('#btnDeleteKB').off('click').on('click', () => requestDeleteKB(kb));

    // 4. Lógica Inteligente de Documentos
    currentDocumentsData = kb.documents || [];
    currentRenderedKBId = kb.kb_id || kb.id;
    const $container = $('#kb-documents-container').empty();
    const $headerContainer = $('#doc-header-container');

    // Escenario A: 0 Documentos
    if (currentDocumentsData.length === 0) {
        $headerContainer.addClass('hidden'); // Ocultar barra
        $container.append('<p class="text-slate-400 text-sm italic p-4">No documents</p>');
        return;
    }

    // Escenario B: 1 Documento
    if (currentDocumentsData.length === 1) {
        $headerContainer.addClass('hidden'); // Ocultar barra, no tiene sentido ordenar 1 item
        renderKBDocument(currentDocumentsData[0], currentRenderedKBId);
        return;
    }

    // Escenario C: 2 o más Documentos
    $headerContainer.removeClass('hidden'); // Mostrar barra

    // Resetear visualmente los botones al estado por defecto (Added: desc)
    $('.doc-sort-btn')
        .attr('data-dir', 'none')
        .removeClass('font-bold text-blue-600')
        .addClass('font-medium text-slate-500 hover:text-slate-800');
    $('.doc-sort-btn .sort-icon').text('↕').addClass('opacity-50');

    const $defaultBtn = $('.doc-sort-btn[data-sort="ingested_at"]');
    $defaultBtn.attr('data-dir', 'desc')
        .removeClass('font-medium text-slate-500 hover:text-slate-800')
        .addClass('font-bold text-blue-600');
    $defaultBtn.find('.sort-icon').text('↓').removeClass('opacity-50');

    // Lanzar el motor de ordenamiento que pinta las tarjetas
    renderSortedDocuments();
}

function renderKBDocument(doc, kbId) {
    const $tpl = $('#tpl-kb-document-item').prop('content');
    const $item = $(document.importNode($tpl, true));
    const $card = $item.find('.js-doc-card');

    $card.attr('data-doi', doc.doi);

    // 1. Datos Principales
    $item.find('.js-doc-title').text(doc.title || 'Untitled Document');
    $item.find('.js-doc-authors').text(doc.authors && doc.authors.length > 0 ? doc.authors.join(', ') : 'Unknown Authors');
    $item.find('.js-doc-abstract').text(doc.abstract || 'No abstract available.');

    // 2. Badges Superiores (Condicionales)
    if (doc.type) {
        $item.find('.js-doc-type').text(doc.type).removeClass('hidden');
    }
    if (doc.year) { // <--- CAMBIADO A doc.year
        $item.find('.js-doc-year').text(doc.year).removeClass('hidden');
    }
    if (doc.file_size) { // <--- CAMBIADO A doc.file_size
        $item.find('.js-doc-size').text(formatBytes(doc.file_size)).removeClass('hidden');
    }
    if (doc.doi) {
        const doiLink = doc.doi.startsWith('http') ? doc.doi : `https://doi.org/${doc.doi}`;
        $item.find('.js-doc-doi').text(doc.doi).attr('href', doiLink).removeClass('hidden');
    }

    // 3. Metadatos Secundarios
    if (doc.venue || doc.publisher) {
        $item.find('.js-doc-venue').text(doc.venue || doc.publisher);
        $item.find('.js-doc-venue-container').removeClass('hidden');
    }
    if (doc.ingested_at) {
        const date = new Date(doc.ingested_at).toLocaleDateString();
        $item.find('.js-doc-added').text(date);
        $item.find('.js-doc-added-container').removeClass('hidden');
    }

    // 4. Topics (Palabras Clave)
    if (doc.keywords && doc.keywords.length > 0) { 
        const $topicsContainer = $item.find('.js-doc-topics');
        doc.keywords.forEach(keyword => {
            $topicsContainer.append(
                `<span class="px-2 py-1 bg-slate-100 border border-slate-200 text-slate-600 rounded text-[10px] uppercase font-bold tracking-wider">${keyword}</span>`
            );
        });
        $item.find('.js-doc-topics-container').removeClass('hidden');
    }

    // 5. EVENTOS: UI y Acciones
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
    // CORRECCIÓN 2: Si el modal no existe en el DOM, lo sacamos del template
    if ($('#modal-kb-select').length === 0) {
        const $tpl = $('#tpl-kb-modal').prop('content');
        $('body').append(document.importNode($tpl, true));

        // Conectamos el botón cancelar del nuevo modal
        $('#btn-modal-cancel').on('click', function() {
            $('#modal-kb-select').addClass('hidden');
        });
    }

    // CORRECCIÓN 3: Llenar el dropdown con las KBs
    const $dropdown = $('#modal-kb-dropdown').empty();
    $dropdown.append('<option value="" disabled selected>Select a Knowledge Base...</option>');
    
    // Pedimos las KBs para que el usuario pueda elegir destino
    $.get('/kbs').done(function(kbs) {
        kbs.forEach(kb => {
            const id = kb.kb_id || kb.id;
            // No mostramos la KB en la que ya estamos
            if (id !== sourceKbId) {
                $dropdown.append(`<option value="${id}">${kb.name}</option>`);
            }
        });
    });

    // Cambiar el texto del botón y deshabilitarlo hasta que elija una opción
    $('#btn-modal-download').prop('disabled', true).text(actionType === 'copy' ? 'Copy Document' : 'Move Document');
    $dropdown.off('change').on('change', function() {
        $('#btn-modal-download').prop('disabled', false);
    });

    // Ahora sí mostramos el modal
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
                    // Si se mueve, desaparece de la vista actual usando el data-doi
                    $(`[data-doi="${doi}"]`).fadeOut(300, function() { $(this).remove(); });
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

let currentKBsData = []; 


function renderSortedKBs() {
    const grid = $('#workspace-grid');
    const $sortBar = $('#kb-sort-bar');
    
    // Vaciamos el grid, pero NO lo forzamos a ser visible incondicionalmente
    grid.empty(); 

    // Solo mostramos el grid si NO estamos dentro de la vista de detalle
    if ($('#workspace-detail').hasClass('hidden')) {
        grid.removeClass('hidden');
    }

    if (!currentKBsData || currentKBsData.length === 0) {
        $sortBar.addClass('hidden');
        grid.html(`
            <div class="col-span-full bg-white border border-slate-200 border-dashed rounded-xl p-12 text-center">
                <p class="text-slate-500 mb-4">You don't have any Knowledge Bases yet.</p>
                <button onclick="openModal()" class="text-blue-600 font-medium hover:underline">Create your first project</button>
            </div>
        `);
        return;
    }

    // LÓGICA DE LA BARRA: Solo se muestra si hay 2 o más KBs Y no estamos en el detalle
    if (currentKBsData.length <= 1) {
        $sortBar.addClass('hidden');
    } else {
        if ($('#workspace-detail').hasClass('hidden')) {
            $sortBar.removeClass('hidden');
        }
    }

    // --- Lógica de Ordenamiento ---
    const $activeBtn = $('.kb-sort-btn').filter(function() {
        return $(this).attr('data-dir') !== 'none';
    }).first();
    
    const sortField = $activeBtn.length ? $activeBtn.data('sort') : 'created_at';
    const sortDir = $activeBtn.length ? $activeBtn.attr('data-dir') : 'desc';

    currentKBsData.sort((a, b) => {
        let valA, valB;
        if (sortField === 'name') {
            valA = (a.name || '').toLowerCase();
            valB = (b.name || '').toLowerCase();
        } else if (sortField === 'docs') {
            valA = a.document_ids ? a.document_ids.length : 0;
            valB = b.document_ids ? b.document_ids.length : 0;
        } else if (sortField === 'created_at') {
            valA = new Date(a.created_at || 0).getTime();
            valB = new Date(b.created_at || 0).getTime();
        }

        if (valA < valB) return sortDir === 'asc' ? -1 : 1;
        if (valA > valB) return sortDir === 'asc' ? 1 : -1;
        return 0;
    });

    // --- Renderizado de Tarjetas ---
    currentKBsData.forEach(kb => {
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

        // Eventos de la tarjeta
        card.on('click', () => loadKBDetail(kb.kb_id || kb.id));
        card.find('.btn-edit-card').on('click', (e) => { e.stopPropagation(); openEditModal(kb); });
        card.find('.btn-delete-card').on('click', (e) => { e.stopPropagation(); requestDeleteKB(kb); });

        grid.append(card);
    });
}

// 4. Los listeners de clics para los botones de arriba
$(document).on('click', '.kb-sort-btn', function(e) {
    e.preventDefault();
    const $btn = $(this);
    const field = $btn.data('sort');
    const currentDir = $btn.attr('data-dir');

    // 1. Determinar nueva dirección
    let nextDir;
    if (currentDir === 'none') {
        // Criterio nuevo: Nombres (asc), Números/Fechas (desc)
        nextDir = (field === 'name') ? 'asc' : 'desc';
    } else {
        // Mismo criterio: Conmutar
        nextDir = (currentDir === 'asc') ? 'desc' : 'asc';
    }

    // 2. Limpiar visualmente todos los botones
    $('.kb-sort-btn').attr('data-dir', 'none')
        .removeClass('font-bold text-blue-600')
        .addClass('font-medium text-slate-500');
    $('.sort-icon').text('↕').addClass('opacity-50');

    // 3. Activar el botón actual
    $btn.attr('data-dir', nextDir)
        .removeClass('font-medium text-slate-500')
        .addClass('font-bold text-blue-600');
    
    $btn.find('.sort-icon').text(nextDir === 'asc' ? '↑' : '↓').removeClass('opacity-50');

    // 4. Ejecutar ordenamiento
    renderSortedKBs();
});

// --- MOTOR DE ORDENAMIENTO Y FILTRADO DE DOCUMENTOS ---
function renderSortedDocuments() {
    const $container = $('#kb-documents-container').empty();
    
    // 1. Obtener el texto del buscador
    const searchTerm = $('#doc-search-input').val() || '';

    // 2. Filtrado Pipeline usando la nueva utilidad
    let filteredDocs = UIUtils.filterByTerms(currentDocumentsData, searchTerm, function(doc) {
        return [
            doc.title || '',
            (doc.authors || []).join(' '),
            (doc.keywords || []).join(' '),
            doc.abstract || '',
            doc.year || ''
        ].join(' ');
    });

    // 3. Control de Estados Vacíos
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

    // 4. Ordenamiento sobre los documentos filtrados
    const $activeBtn = $('.doc-sort-btn').filter(function() {
        return $(this).attr('data-dir') !== 'none';
    }).first();
    
    const sortField = $activeBtn.length ? $activeBtn.data('sort') : 'ingested_at';
    const sortDir = $activeBtn.length ? $activeBtn.attr('data-dir') : 'desc';

    filteredDocs.sort((a, b) => {
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
        return 0;
    });

    // 5. Pintar en UI
    filteredDocs.forEach(doc => {
        renderKBDocument(doc, currentRenderedKBId);
    });
}

$(document).off('click', '.doc-sort-btn').on('click', '.doc-sort-btn', function(e) {
    e.preventDefault();
    const $btn = $(this);
    const field = $btn.data('sort');
    const currentDir = $btn.attr('data-dir');

    let nextDir;
    if (currentDir === 'none' || !currentDir) {
        nextDir = (field === 'title') ? 'asc' : 'desc';
    } else {
        nextDir = (currentDir === 'asc') ? 'desc' : 'asc';
    }

    $('.doc-sort-btn')
        .attr('data-dir', 'none')
        .removeClass('font-bold text-blue-600')
        .addClass('font-medium text-slate-500 hover:text-slate-800');
    $('.doc-sort-btn .sort-icon').text('↕').addClass('opacity-50');

    $btn.attr('data-dir', nextDir)
        .removeClass('font-medium text-slate-500 hover:text-slate-800')
        .addClass('font-bold text-blue-600');
    
    $btn.find('.sort-icon').text(nextDir === 'asc' ? '↑' : '↓').removeClass('opacity-50');

    renderSortedDocuments();
});

// ESCUCHADOR DEL BUSCADOR (Reacciona al teclear)
$(document).off('input', '#doc-search-input').on('input', '#doc-search-input', function() {
    renderSortedDocuments();
});