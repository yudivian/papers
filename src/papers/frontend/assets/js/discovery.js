
/**
 * Papers Discovery & Task Monitor
 */

let pendingData = { doi: null, title: null };

let availableSources = []; // <-- VARIABLE NUEVA PARA GUARDAR LAS FUENTES



// =====================================================================
// BLOQUE PRINCIPAL (Al cargar la página)
// =====================================================================
$(document).ready(function () {

    // ---------------------------------------------------------
    // 1. LO QUE YA TENÍAS (Carga de componentes y DOI)
    // ---------------------------------------------------------
    $.get('/components/doi_card.html', function (html) {
        $('body').append(html);
        const modalTpl = document.getElementById('tpl-kb-modal');
        if (modalTpl) {
            document.body.appendChild(modalTpl.content.cloneNode(true));
            setupModalListeners(); // Asegúrate de que esta función exista más abajo
        }
        // restoreTasks();
    });

    $('#btn-search-doi').on('click', handleDoiSearch);

    // ---------------------------------------------------------
    // 2. LÓGICA DE PESTAÑAS (TABS)
    // ---------------------------------------------------------
    $('#tab-btn-doi').on('click', function () {
        $(this).addClass('border-blue-600 text-blue-600').removeClass('border-transparent text-slate-500');
        $('#tab-btn-text').removeClass('border-blue-600 text-blue-600').addClass('border-transparent text-slate-500');
        $('#tab-content-doi').removeClass('hidden').addClass('block');
        $('#tab-content-text').removeClass('block').addClass('hidden');
        $('#discovery-results').empty();
    });

    $('#tab-btn-text').on('click', function () {
        $(this).addClass('border-blue-600 text-blue-600').removeClass('border-transparent text-slate-500');
        $('#tab-btn-doi').removeClass('border-blue-600 text-blue-600').addClass('border-transparent text-slate-500');
        $('#tab-content-text').removeClass('hidden').addClass('block');
        $('#tab-content-doi').removeClass('block').addClass('hidden');
        $('#discovery-results').empty();
    });

    // ---------------------------------------------------------
    // 3. INICIALIZAR FUENTES Y CHECKBOXES
    // ---------------------------------------------------------
    $.get('/api/v1/sources', function (sources) {
        const hasCache = sources.some(s => s.id === 'cache');
        if (!hasCache) {
            sources.unshift({ id: 'cache', name: 'Local Cache' });
        }

        availableSources = sources;
        const $container = $('#sources-checkboxes-container');

        availableSources.forEach(src => {
            const icon = src.id === 'cache' ? '📦' : '🌐';
            $container.append(`
                <label class="flex items-center gap-2 text-sm font-medium text-slate-600 cursor-pointer select-none source-label transition-opacity opacity-50">
                    <input type="checkbox" class="source-checkbox rounded border-slate-300 text-blue-600 focus:ring-blue-500" value="${src.id}" disabled>
                    ${icon} ${src.name}
                </label>
            `);
        });
    });

    $('#chk-all-sources').on('change', function () {
        const isChecked = $(this).is(':checked');
        $('.source-checkbox').prop('disabled', isChecked);
        if (isChecked) {
            $('.source-checkbox').prop('checked', false);
            $('.source-label').addClass('opacity-50');
        } else {
            $('.source-label').removeClass('opacity-50');
        }
    });

    // ---------------------------------------------------------
    // 4. EL MOTOR PROGRESIVO DE BÚSQUEDA TEXTUAL
    // ---------------------------------------------------------
    $('#btn-search-text').on('click', function () {
        const query = $('#text-search-input').val().trim();
        const limit = $('#search-limit-input').val() || 10;

        if (isNaN(limit) || limit < 1) {
            limit = 10;
            $('#search-limit-input').val(10);
        } else if (limit > 50) {
            limit = 50;
            $('#search-limit-input').val(50); // Le bajamos el número visualmente al usuario
            if (window.showToast) window.showToast('Maximum allowed limit is 50 per source.', 'info');
        }

        if (!query) {
            if (window.showToast) window.showToast('Please enter a search term.', 'warning');
            return;
        }

        let targetSources = [];
        if ($('#chk-all-sources').is(':checked')) {
            targetSources = availableSources.map(s => s.id);
        } else {
            $('.source-checkbox:checked').each(function () {
                targetSources.push($(this).val());
            });
        }

        if (targetSources.length === 0) {
            if (window.showToast) window.showToast('Please select at least one source.', 'warning');
            return;
        }

        const $results = $('#discovery-results');
        $results.empty();

        // Ordenamos para que 'cache' sea siempre el primero
        targetSources.sort((a, b) => a === 'cache' ? -1 : (b === 'cache' ? 1 : 0));

        targetSources.forEach(sourceId => {
            const sourceInfo = availableSources.find(s => s.id === sourceId);
            const sourceName = sourceInfo ? sourceInfo.name : sourceId;
            const isCache = sourceId === 'cache';
            const color = isCache ? 'emerald' : 'blue';
            const icon = isCache ? '📦' : '🌐';

            // Dibujar el esqueleto de carga
            $results.append(`
                <div id="results-block-${sourceId}" class="mb-8">
                    <div class="mb-4 pb-2 border-b-2 border-${color}-100 flex items-center justify-between">
                        <h3 class="text-sm font-bold text-${color}-700 uppercase tracking-widest flex items-center gap-2">
                            <span>${icon}</span> Searching in ${sourceName}...
                        </h3>
                        <svg class="animate-spin h-5 w-5 text-${color}-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                        </svg>
                    </div>
                    <div class="results-content"></div>
                </div>
            `);

            // Disparar AJAX independiente
            $.ajax({
                url: '/api/v1/discovery/search',
                type: 'GET',
                data: { q: query, limit: limit, source: sourceId },
                success: function (response) {
                    const $block = $(`#results-block-${sourceId}`);
                    const $content = $block.find('.results-content');
                    $block.find('.animate-spin').remove();

                    const docs = response[sourceId] || [];

                    if (docs.length === 0) {
                        $block.find('h3').html(`<span>${icon}</span> Found in ${sourceName} (0)`);
                        $content.html(`<p class="text-sm text-slate-500 italic py-2">No documents found.</p>`);
                        return;
                    }

                    $block.find('h3').html(`<span>${icon}</span> Found in ${sourceName} (${docs.length})`);
                    docs.forEach(doc => renderDoiCard(doc, $content));
                },
                error: function () {
                    const $block = $(`#results-block-${sourceId}`);
                    $block.find('.animate-spin').remove();
                    $block.find('h3').html(`<span>${icon}</span> Error fetching from ${sourceName}`);
                    $block.find('.results-content').html(`<p class="text-sm text-red-500 font-medium py-2">Failed to retrieve data from this source.</p>`);
                }
            });
        });
    });

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
        const $doiElement = $item.find('.js-doc-doi');
        
        // 1. Verificamos que el backend no lo haya marcado explícitamente como falso
        const isOfficialBackend = meta.is_official_doi !== false;
        
        // 2. Lo pasamos por tu validador de regex del frontend
        const sanitizedDoi = sanitizeAndValidateDoi(meta.doi);

        // Si pasa AMBAS pruebas, es un DOI real: construimos el link y lo mostramos
        if (isOfficialBackend && sanitizedDoi) {
            const doiLink = sanitizedDoi.startsWith('http') ? sanitizedDoi : `https://doi.org/${sanitizedDoi}`;
            $doiElement.text(sanitizedDoi).attr('href', doiLink).removeClass('hidden');
        } else {
            // Es un ID interno (ej. core:11469887). Lo ocultamos completamente de la interfaz.
            $doiElement.addClass('hidden');
        }
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

        // MVP: Validar si es realmente descargable
        // Asumimos is_official_doi como true por defecto si no viene
        const isOfficial = meta.is_official_doi !== false;
        const hasStorage = !!meta.storage_uri;

        if (!isOfficial && !hasStorage) {
            // BLOQUEO: No es oficial y no tiene link de descarga. Solo metadatos.
            $btnAction
                .addClass('bg-slate-100 text-slate-500 cursor-not-allowed')
                .html('<i class="fas fa-info-circle"></i> Metadata Only')
                .prop('disabled', true);
        } else {
            // NORMAL: Es oficial o tiene link directo.
            $btnAction
                .addClass('bg-blue-600 hover:bg-blue-700 text-white')
                .html('<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path></svg> Confirm & Download')
                .on('click', function () {
                    // AQUÍ ESTÁ LA MAGIA: Guardamos todos los datos extra para el backend
                    pendingData = {
                        doi: meta.doi,
                        title: meta.title,
                        intent: 'download',
                        source: meta.source,                   // ¡Nuevo!
                        is_official_doi: meta.is_official_doi, // ¡Nuevo!
                        storage_uri: meta.storage_uri          // ¡Nuevo!
                    };
                    $('#modal-paper-title').text(meta.title);
                    $('#modal-kb-select').removeClass('hidden');
                    loadKbList();
                });
        }
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
            executeIngestion(pendingData, kbId);
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

function executeIngestion(data, kbId) {
    $.ajax({
        url: '/ingestion/start',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({
            doi: data.doi,
            title: data.title,
            kb_id: kbId,
            // Enviamos el contexto completo que necesitaba el worker (Bloque 3)
            source: data.source,
            is_official_doi: data.is_official_doi,
            storage_uri: data.storage_uri
        }),
        success: (res) => {
            window.showToast('Download started', 'success');
            trackTask(res.ticket_id, data.title, 'PENDING');
            $('#downloads-backdrop').removeClass('hidden');
            $('#downloadsPanel').removeClass('translate-x-full');
        }
    });
}

/**
 * GESTIÓN DE TAREAS (Monitor lateral)
 */









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

