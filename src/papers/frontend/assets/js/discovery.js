let pendingData = { doi: null, title: null };

function sanitizeAndValidateDoi(input) {
    let clean = input.trim().replace(/^(https?:\/\/)?(dx\.)?doi\.org\//i, '').replace(/^doi:\s*/i, '');
    return /^10\.\d{4,9}\/[-._;()/:a-zA-Z0-9]+$/i.test(clean) ? clean : null;
}

$(document).ready(function() {
    // 1. CARGA DE COMPONENTES
    $.get('/components/doi_card.html', function(data) {
        $('body').append(data); // Inyecta los templates
        
        // MATERIALIZAR EL MODAL: Hay que sacarlo del template para que exista en el DOM
        const modalTemplate = document.getElementById('tpl-kb-modal');
        if (modalTemplate) {
            const modalContent = modalTemplate.content.cloneNode(true);
            document.body.appendChild(modalContent);
        }
        
        // 2. ACTIVAR LISTENERS (Solo cuando el modal ya existe)
        setupModalListeners();
        restoreActiveDownloads();
        
        // 3. VINCULAR BÚSQUEDA
        $('#btn-search-doi').on('click', handleDoiSearch);
    }).fail(function() {
        console.error("Critical: Could not load doi_card.html component.");
    });
});

function handleDoiSearch() {
    const doi = sanitizeAndValidateDoi($('#doi-input').val());
    if (!doi) {
        window.showToast('Please enter a valid DOI.', 'error');
        return;
    }

    const $container = $('#discovery-results');
    $container.html('<div class="p-12 text-center text-slate-400 animate-pulse font-medium">Resolving DOI metadata...</div>');

    $.ajax({
        url: `/discovery/doi/${encodeURIComponent(doi)}`,
        type: 'GET',
        success: (meta) => renderDoiCard(meta, $container),
        error: () => $container.html('<div class="p-6 bg-red-50 text-red-600 rounded-xl border border-red-100 text-sm">DOI could not be resolved.</div>')
    });
}

function renderDoiCard(meta, $container) {
    const template = document.getElementById('tpl-doi-card');
    if (!template) return;
    
    const clone = template.content.cloneNode(true);
    clone.querySelector('.js-card-title').textContent = meta.title;
    clone.querySelector('.js-card-doi').textContent = meta.doi;
    
    if (meta.abstract) {
        const abs = clone.querySelector('.js-card-abstract');
        abs.textContent = meta.abstract;
        abs.classList.remove('hidden');
    }
    
    clone.querySelector('.js-btn-confirm').addEventListener('click', () => {
        pendingData = { doi: meta.doi, title: meta.title };
        $('#modal-paper-title').text(meta.title);
        $('#modal-kb-select').removeClass('hidden'); // Ahora SÍ funcionará
        loadKbList();
    });

    $container.empty().append(clone);
}

function setupModalListeners() {
    // Delegación de eventos para el modal recién inyectado
    $(document).on('change', '#modal-kb-dropdown', function() {
        $('#btn-modal-download').prop('disabled', !$(this).val());
    });

    $(document).on('click', '#btn-modal-cancel', function() {
        $('#modal-kb-select').addClass('hidden');
    });

    $(document).on('click', '#btn-modal-download', function() {
        const kbId = $('#modal-kb-dropdown').val();
        $('#modal-kb-select').addClass('hidden');
        executeIngestion(pendingData.doi, pendingData.title, kbId);
    });
}

function loadKbList() {
    const $select = $('#modal-kb-dropdown');
    $select.html('<option value="" disabled selected>Loading Knowledge Bases...</option>');
    
    $.ajax({
        url: '/kbs', // Tu router kbs.py
        type: 'GET',
        success: (kbs) => {
            let options = '<option value="" disabled selected>Select destination...</option>';
            kbs.forEach(kb => options += `<option value="${kb.kb_id}">${kb.name}</option>`);
            $select.html(options);
        }
    });
}

function executeIngestion(doi, title, kbId) {
    $.ajax({
        url: '/ingestion/start',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ doi: doi, title: title, kb_id: kbId }),
        success: (res) => {
            window.showToast('Ingestion started.', 'success');
            trackTask(res.ticket_id, title);
            $('#discovery-results').empty();
            $('#doi-input').val('');
        }
    });
}

function trackTask(ticketId, title) {
    if ($(`#task-${ticketId}`).length) return;

    const template = document.getElementById('tpl-task-item');
    const clone = template.content.cloneNode(true);
    const $card = $(clone.querySelector('.js-task-card')).attr('id', `task-${ticketId}`);
    
    $card.find('.js-task-title').text(title);
    $('#taskList').prepend($card);

    const interval = setInterval(() => {
        $.ajax({
            url: `/ingestion/status/${ticketId}`,
            type: 'GET',
            success: (data) => {
                const $t = $(`#task-${ticketId}`);
                const $label = $t.find('.js-task-status');
                const $bar = $t.find('.js-task-progress');

                $label.text(data.status);
                if (data.status === 'DOWNLOADING') {
                    $bar.css('width', '60%');
                } else if (data.status === 'COMPLETED') {
                    $bar.css('width', '100%').addClass('bg-emerald-500');
                    $label.text('DONE').addClass('text-emerald-600');
                    clearInterval(interval);
                    setTimeout(() => $t.fadeOut(() => $t.remove()), 8000);
                } else if (data.status === 'FAILED') {
                    clearInterval(interval);
                    $bar.addClass('bg-red-500').css('width', '100%');
                    $t.find('.js-task-error').text(data.error_message || 'Error').removeClass('hidden');
                }
            },
            error: () => clearInterval(interval)
        });
    }, 3000);
}

function restoreActiveDownloads() {
    $.ajax({
        url: '/ingestion/active',
        type: 'GET',
        success: (tasks) => tasks.forEach(t => trackTask(t.ticket_id, t.title))
    });
}