/**
 * Papers Discovery & Task Monitor
 * Lógica de búsqueda por DOI y gestión manual de ingesta.
 */

let pendingData = { doi: null, title: null };
let taskIntervals = {}; // Control de polling por ticket

function sanitizeAndValidateDoi(input) {
    let clean = input.trim().replace(/^(https?:\/\/)?(dx\.)?doi\.org\//i, '').replace(/^doi:\s*/i, '');
    return /^10\.\d{4,9}\/[-._;()/:a-zA-Z0-9]+$/i.test(clean) ? clean : null;
}

$(document).ready(function () {
    // 1. Cargar componentes e inicializar el monitor
    $.get('/components/doi_card.html', function (html) {
        $('body').append(html);

        // Extraer y activar el modal
        const modalTpl = document.getElementById('tpl-kb-modal');
        if (modalTpl) {
            document.body.appendChild(modalTpl.content.cloneNode(true));
            setupModalListeners();
        }

        // Cargar historial de tareas del usuario
        restoreTasks();
    });

    // 2. Listener de búsqueda
    $('#btn-search-doi').on('click', handleDoiSearch);
});

function handleDoiSearch() {
    const doi = sanitizeAndValidateDoi($('#doi-input').val());
    if (!doi) {
        window.showToast('Invalid DOI format.', 'error');
        return;
    }

    const $container = $('#discovery-results');
    $container.html('<div class="p-12 text-center text-slate-400 animate-pulse font-medium">Resolving metadata...</div>');

    $.ajax({
        url: `/discovery/doi/${encodeURIComponent(doi)}`,
        type: 'GET',
        success: (meta) => renderDoiCard(meta, $container),
        error: () => $container.html('<div class="p-6 bg-red-50 text-red-600 rounded-xl border border-red-100 text-sm">Metadata not found.</div>')
    });
}

function renderDoiCard(meta, $container) {
    const $tpl = $('#tpl-doi-card').prop('content');
    const $item = $(document.importNode($tpl, true));
    const $card = $item.find('.js-doc-card');

    // 1. Mapeo de Datos Básicos
    $item.find('.js-doc-title').text(meta.title || 'Untitled Document');
    $item.find('.js-doc-authors').text(meta.authors && meta.authors.length > 0 ? meta.authors.join(', ') : 'Unknown Authors');
    $item.find('.js-doc-abstract').text(meta.abstract || 'No abstract available.');

    if (meta.year) {
        $item.find('.js-doc-year').text(meta.year).removeClass('hidden');
    }
    if (meta.doi) {
        const doiLink = meta.doi.startsWith('http') ? meta.doi : `https://doi.org/${meta.doi}`;
        $item.find('.js-doc-doi').text(meta.doi).attr('href', doiLink).removeClass('hidden');
    }
    if (meta.source) {
        $item.find('.js-doc-source').text(meta.source).removeClass('hidden');
    }

    // 2. Mapeo de Keywords 
    if (meta.keywords && meta.keywords.length > 0) {
        const $topicsContainer = $item.find('.js-doc-topics');
        meta.keywords.slice(0, 8).forEach(keyword => {
            $topicsContainer.append(
                `<span class="px-2 py-1 bg-white border border-slate-200 text-slate-600 rounded text-[10px] uppercase font-bold tracking-wider">${keyword}</span>`
            );
        });
        $item.find('.js-doc-topics-container').removeClass('hidden');
    }

    // 3. Evento: Desplegar Abstract
    $item.find('.js-btn-toggle-meta').on('click', function () {
        $card.find('.js-doc-meta-panel').slideToggle(250);
    });

    // 4. LÓGICA DEL BOTÓN PRINCIPAL
    const $btnAction = $item.find('.js-btn-action');
    const $statusMsg = $item.find('.js-status-msg');

    // Evaluamos EXACTAMENTE el string que manda tu backend
    if (meta.source === 'cache') {
        // Estado: Ya lo tienes en la caché local
        $statusMsg.text('Located in local cache');
        $btnAction
            .addClass('bg-emerald-600 hover:bg-emerald-700 text-white')
            .html('<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7v8a2 2 0 002 2h6M8 7V5a2 2 0 012-2h4.586a1 1 0 01.707.293l4.414 4.414a1 1 0 01.293.707V15a2 2 0 01-2 2h-2M8 7H6a2 2 0 00-2 2v10a2 2 0 002 2h8a2 2 0 002-2v-2"></path></svg> Confirm & Copy')
            .on('click', function () {
                // AQUÍ ESTÁ LA MAGIA: Guardamos la intención de "copiar"
                pendingData = { doi: meta.doi, title: meta.title, intent: 'copy' };
                $('#modal-paper-title').text(meta.title);
                $('#modal-kb-select').removeClass('hidden');
                loadKbList();
            });
    } else {
        // Estado: Nuevo paper (OpenAlex, etc.)
        $statusMsg.text('Found via ' + (meta.source || 'external search'));
        $btnAction
            .addClass('bg-blue-600 hover:bg-blue-700 text-white')
            .html('<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path></svg> Confirm & Download')
            .on('click', function () {
                // AQUÍ ESTÁ LA MAGIA: Guardamos la intención de "descargar"
                pendingData = { doi: meta.doi, title: meta.title, intent: 'download' };
                $('#modal-paper-title').text(meta.title);
                $('#modal-kb-select').removeClass('hidden');
                loadKbList();
            });
    }

    // Limpiamos y añadimos (igual que antes)
    if ($container.attr('id') === 'discovery-results') {
        $container.empty().append($item);
    } else {
        $container.append($item);
    }
}

function setupModalListeners() {
    $(document).on('change', '#modal-kb-dropdown', function () {
        $('#btn-modal-download').prop('disabled', !$(this).val());
    });

    $(document).on('click', '#btn-modal-cancel', () => $('#modal-kb-select').addClass('hidden'));

    // Dentro de setupModalListeners() o donde tengas este evento:
    $('#btn-modal-download').off('click').on('click', function () {
        const kbId = $('#modal-kb-dropdown').val();
        if (!kbId) {
            if (window.showToast) window.showToast('Please select a Knowledge Base', 'error');
            return;
        }

        // Ocultar modal inmediatamente
        $('#modal-kb-select').addClass('hidden');

        // BIFURCACIÓN BASADA EN LA INTENCIÓN
        if (pendingData.intent === 'copy') {
            // ----------------------------------------------------
            // RUTA RÁPIDA: Vinculación directa al endpoint nuevo
            // ----------------------------------------------------
            executeCopy(pendingData.doi, kbId)

        } else {
            executeIngestion(pendingData.doi, pendingData.title, kbId);
        }
    });
}

function loadKbList() {
    const $select = $('#modal-kb-dropdown');
    $select.html('<option value="" disabled selected>Loading KBs...</option>');
    $.get('/kbs', (kbs) => {
        let html = '<option value="" disabled selected>Select KB...</option>';
        kbs.forEach(kb => html += `<option value="${kb.kb_id}">${kb.name}</option>`);
        $select.html(html);
    });
}

function executeCopy(doi, kbId) {
    $.ajax({
        url: `/kbs/${kbId}/documents`, // <-- Nueva ruta limpia
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({
            dois: [doi] // <-- Mandamos solo los DOIs
        }),
        success: function (response) {
            if (window.showToast) {
                window.showToast('Document linked from cache successfully!', 'success');
            }
            $('#doi-input').val('');
        },
        error: function (xhr) {
            console.error("Error linking doc:", xhr.responseText);
            if (window.showToast) {
                window.showToast('Error linking document from cache.', 'error');
            }
        }
    });
}

function executeIngestion(doi, title, kbId) {
    $.ajax({
        url: '/ingestion/start',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ doi, title, kb_id: kbId }),
        success: (res) => {
            window.showToast('Download started', 'success');
            trackTask(res.ticket_id, title, 'PENDING');
            $('#discovery-results').empty();
            $('#doi-input').val('');
        }
    });
}

/**
 * GESTIÓN DE TAREAS (Monitor lateral)
 */

function restoreTasks() {
    Object.values(taskIntervals).forEach(clearInterval);
    taskIntervals = {};
    $('#taskList').empty();

    $.get('/ingestion/tasks', (tasks) => {
        tasks.forEach(t => trackTask(t.ticket_id, t.title, t.status));
    });
}

function trackTask(ticketId, title, initialStatus) {
    if ($(`#task-${ticketId}`).length) return;

    const template = document.getElementById('tpl-task-item');
    const clone = template.content.cloneNode(true);
    const $card = $(clone.querySelector('.js-task-card')).attr('id', `task-${ticketId}`);

    $card.find('.js-task-title').text(title);
    $('#taskList').prepend($card);

    // --- ACCIÓN: CANCELAR ---
    $card.find('.js-btn-cancel-task').on('click', function () {
        showConfirmModal('Cancel Download', `Stop downloading "${title}"?`, function () {
            $.ajax({
                url: `/ingestion/cancel/${ticketId}`,
                type: 'POST',
                success: function () {
                    if (taskIntervals[ticketId]) {
                        clearInterval(taskIntervals[ticketId]);
                        delete taskIntervals[ticketId];
                    }
                    updateTaskUI(ticketId, 'CANCELLED');
                    window.showToast('Download cancelled', 'info');
                }
            });
        });
    });

    // --- ACCIÓN: ELIMINAR ---
    $card.find('.js-btn-delete-task').on('click', function () {
        showConfirmModal('Delete Record', `Permanently remove "${title}" from the list?`, function () {
            $.ajax({
                url: `/ingestion/${ticketId}`, // <--- CORREGIDO: Sin /api/v1
                type: 'DELETE',
                success: function () {
                    $card.fadeOut(300, () => $card.remove());
                    window.showToast('Record deleted', 'success');
                }
            });
        });
    });

    updateTaskUI(ticketId, initialStatus);

    if (['PENDING', 'DOWNLOADING'].includes(initialStatus)) {
        startPolling(ticketId);
    }
}

function startPolling(ticketId) {
    if (taskIntervals[ticketId]) return;

    taskIntervals[ticketId] = setInterval(() => {
        $.get(`/ingestion/status/${ticketId}`, (data) => {
            // 1. Actualiza la UI
            updateTaskUI(ticketId, data.status, data.error_message);
            
            // 2. Normalizamos el string (igual que hace la función visual)
            const safeStatus = String(data.status || 'PENDING').trim().toUpperCase();
            
            // 3. LA MAGIA: Mantenemos vivo el polling en TODOS los estados activos
            if (!['PENDING', 'DOWNLOADING', 'PROCESSING'].includes(safeStatus)) {
                clearInterval(taskIntervals[ticketId]);
            }
            
        }).fail(() => {
            // Si el servidor falla temporalmente, no abortamos el polling para siempre
            // solo dejamos que lo intente en el siguiente ciclo, o si prefieres matar:
            clearInterval(taskIntervals[ticketId]);
        });
    }, 3000); // Preguntamos cada 3 segundos
}

function showConfirmModal(title, message, onConfirm) {
    const $modal = $('#modal-custom-confirm');

    $modal.find('.js-confirm-title').text(title);
    $modal.find('.js-confirm-message').text(message);
    $modal.removeClass('hidden');

    // Desvincular eventos pasados
    $modal.find('.js-confirm-cancel, .js-confirm-accept').off('click');

    $modal.find('.js-confirm-cancel').on('click', () => $modal.addClass('hidden'));
    $modal.find('.js-confirm-accept').on('click', () => {
        $modal.addClass('hidden');
        if (typeof onConfirm === 'function') onConfirm();
    });
}

function updateTaskUI(ticketId, status, errorMsg = '') {
    const $card = $(`#task-${ticketId}`);
    if (!$card.length) return;

    const $bullet = $card.find('.js-task-bullet');
    const $text = $card.find('.js-task-status-text');
    const $error = $card.find('.js-task-error');

    // 1. Diccionario completo (Añadido PROCESSING)
    const theme = {
        'PENDING': { bullet: 'bg-slate-300', text: 'text-slate-500', label: 'PENDING' },
        'DOWNLOADING': { bullet: 'bg-blue-500 animate-pulse', text: 'text-blue-600', label: 'DOWNLOADING' },
        'PROCESSING': { bullet: 'bg-purple-500 animate-pulse', text: 'text-purple-600', label: 'PROCESSING' },
        'COMPLETED': { bullet: 'bg-emerald-500', text: 'text-emerald-600', label: 'SUCCESS' },
        'FAILED': { bullet: 'bg-orange-500', text: 'text-orange-600', label: 'FAILED' },
        'CANCELLED': { bullet: 'bg-red-500', text: 'text-red-600', label: 'CANCELLED' }
    };

    // 2. Limpieza extrema del estado que manda el servidor
    // String() evita que reviente si llega null, trim() quita espacios, toUpperCase() lo normaliza
    const safeStatus = String(status || 'PENDING').trim().toUpperCase();

    // Si aún así llega un estado rarísimo, usamos el por defecto pero hacemos un console.log para avisarte
    const style = theme[safeStatus] || theme['PENDING'];

    if (!theme[safeStatus]) {
        console.warn(`Estado desconocido recibido del backend: "${status}". Se mostrará como PENDING.`);
    }

    // 3. Limpiamos cualquier clase vieja
    $bullet.removeClass('bg-slate-300 bg-blue-500 bg-purple-500 bg-emerald-500 bg-orange-500 bg-red-500 animate-pulse');
    $text.removeClass('text-slate-500 text-blue-600 text-purple-600 text-emerald-600 text-orange-600 text-red-600');

    // 4. Aplicamos el color y texto correcto
    $bullet.addClass(style.bullet);
    $text.addClass(style.text).text(style.label);

    // 5. Manejo de errores
    if (['FAILED', 'CANCELLED'].includes(safeStatus) && errorMsg) {
        $error.text(errorMsg).removeClass('hidden');
    } else {
        $error.addClass('hidden');
    }

    const isActive = ['PENDING', 'DOWNLOADING', 'PROCESSING'].includes(safeStatus);

    if (isActive) {
        $card.find('.js-btn-cancel-task').removeClass('hidden');
        $card.find('.js-btn-delete-task').addClass('hidden');
    } else {
        $card.find('.js-btn-cancel-task').addClass('hidden');
        $card.find('.js-btn-delete-task').removeClass('hidden');
    }
}

// En src/papers/frontend/assets/js/workspace.js

function renderKBDocument(doc, kbId) {
    const $tpl = $('#tpl-kb-document-item').prop('content');
    const $item = $(document.importNode($tpl, true));
    const $card = $item.find('.js-doc-card');

    // Poblar datos por nombre/título
    $item.find('.js-doc-title').text(doc.title || 'Untitled Document');
    $item.find('.js-doc-doi').text(doc.doi);
    $item.find('.js-doc-year').text(doc.publication_year || 'N/A');
    $item.find('.js-doc-authors').text(doc.authors ? doc.authors.join(', ') : 'Unknown Authors');
    $item.find('.js-doc-abstract').text(doc.abstract || 'No abstract available.');

    // Toggle de metadatos
    $item.find('.js-btn-toggle-meta').on('click', function () {
        $card.find('.js-doc-meta-panel').slideToggle(200);
    });

    // Acción: COPIAR (Usa el nuevo endpoint)
    $item.find('.js-btn-copy-doc').on('click', function () {
        openTransferModal('copy', doc.doi, kbId);
    });

    // Acción: MOVER (Usa el endpoint transfer existente)
    $item.find('.js-btn-move-doc').on('click', function () {
        openTransferModal('transfer', doc.doi, kbId);
    });

    // Acción: ELIMINAR (Unlink)
    $item.find('.js-btn-unlink-doc').on('click', function () {
        window.showConfirmModal(
            'Remove Document',
            `Unlink "${doc.title}" from this Knowledge Base?`,
            function () {
                $.ajax({
                    url: `/kbs/${kbId}/documents/${encodeURIComponent(doc.doi)}`,
                    type: 'DELETE',
                    success: function () {
                        $card.fadeOut(300, () => $card.remove());
                        window.showToast('Document unlinked', 'success');
                    }
                });
            }
        );
    });

    $('#kb-documents-container').append($item);
}

/**
 * Lógica compartida para Mover/Copiar
 */
function openTransferModal(actionType, doi, sourceKbId) {
    // Aquí abrirías el modal de selección de KB que ya tienes.
    // Al seleccionar la 'targetKbId' y confirmar:
    const url = `/kbs/${targetKbId}/${actionType}`;
    $.ajax({
        url: url,
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({
            dois: [doi],
            source_kb_id: sourceKbId
        }),
        success: function () {
            if (actionType === 'transfer') {
                $(`[data-doi="${doi}"]`).fadeOut(); // Si movió, quitamos de la vista actual
            }
            window.showToast(`Document ${actionType}ed successfully`, 'success');
        }
    });
}