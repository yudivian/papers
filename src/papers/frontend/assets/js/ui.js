/**
 * UI Utilities and Shared Components Logic
 */

const UI = {
    /**
     * Loads the sidebar and automatically highlights the active link
     * based on the current URL.
     */
    loadSidebar: function () {
        $('#sidebar-container').load('/components/sidebar.html', function () {
            // 1. Obtenemos la ruta exacta (ej: /index.html)
            let path = window.location.pathname;
            if (path === '/' || path === '') path = '/index.html';

            // 2. Limpiamos todos los links usando tus clases de slate
            $('#mainSidebar nav a')
                .removeClass('bg-slate-800 text-white font-bold')
                .addClass('text-slate-300');

            // 3. Resaltamos el link que coincide exactamente con el href
            $(`#mainSidebar nav a[href="${path}"]`)
                .removeClass('text-slate-300')
                .addClass('bg-slate-800 text-white font-bold');

            if (typeof getAuthToken === 'function') {
                $('#session-name').text(getAuthToken());
            }
            $.ajax({
                url: '/orcid/settings',
                type: 'GET',
                success: function(response) {
                    if (response.is_enabled && response.has_orcid) {
                        $('#navOrcidProfile').removeClass('hidden');
                    }
                }
            });
        });
    },
    loadDownloadsPanel: function () {
        $.get('/components/downloads_panel.html', function (html) {
            $('body').append(html);
            if (typeof restoreTasks === 'function') {
                restoreTasks();
            }
        });
    },

    // Actualiza el número de tareas activas
    updateDownloadsBadge: function () {
        let activeCount = $('#taskList .animate-pulse').length;
        if (activeCount > 0) {
            $('#downloadsBadge').text(activeCount).removeClass('hidden');
        } else {
            $('#downloadsBadge').addClass('hidden');
        }
    }
};

$(document).ready(function () {
    UI.loadSidebar();
    UI.loadDownloadsPanel();

    if (typeof getAuthToken === 'function') {
        const userToken = getAuthToken();
        if (userToken) {
            // Lo ponemos en el header (el que está al lado de "Session:")
            $('#displayUser').text(userToken);

            // Y por si acaso, intentamos ponerlo en el sidebar (si ya cargó)
            $('#session-name').text(userToken);
        }
    }

    $(document).on('click', '#openSidebarMobileBtn', function () {
        $('#mobileSidebarOverlay').removeClass('hidden');
        setTimeout(() => {
            $('#mobileSidebarOverlay').removeClass('opacity-0').addClass('opacity-100');
            $('#mainSidebar').removeClass('-translate-x-full');
        }, 10);
    });

    // Eventos delegados para abrir/cerrar el panel deslizante (Sin bloqueo)
    // Eventos delegados para abrir/cerrar el panel deslizante (Sin bloqueo)
    $(document).on('click', '#openDownloadsBtn', function () {
        // 1. Elevamos Downloads por encima de Settings temporalmente
        $('#downloadsPanel').css('z-index', 65);
        $('#settingsPanel').css('z-index', 60);

        // 2. Exclusión mutua (animación)
        $('#settingsPanel').addClass('translate-x-full');
        $('#downloadsPanel').removeClass('translate-x-full');
    });

    $(document).on('click', '#closeDownloadsBtn, #downloads-backdrop', function () {
        $('#downloads-backdrop').addClass('hidden');
        $('#downloadsPanel').addClass('translate-x-full');
    });

    $.get('/components/usage_panel.html', function (html) {
        $('body').append(html);
    });

    // EVENTO ABRIR: Con prioridad máxima y refresco de datos
    $(document).on('click', '#openUsageBtn', function () {
        // 1. Ponemos el z-index de Usage por encima de cualquier otro dinámico (ej: 65)
        $('#usagePanel').css('z-index', 80);
        $('#usage-backdrop').css('z-index', 70);

        // 2. Mostramos
        $('#usage-backdrop').removeClass('hidden');
        $('#usagePanel').removeClass('translate-x-full');

        // 3. ACTUALIZACIÓN REAL (sin alucinaciones)
        window.refreshUsageMetrics();
    });

    // EVENTO CERRAR
    // EVENTO CERRAR
    $(document).on('click', '#closeUsageBtn, #usage-backdrop', function () {
        $('#usage-backdrop').addClass('hidden');
        $('#usagePanel').addClass('translate-x-full');
    });

    // --- CREACIÓN INLINE DE KBs ---
    // --- CREACIÓN INLINE DE KBs (Global y dinámico) ---
$(document).on('click', '.js-btn-reveal-new-kb', function() {
    // Busca el cuadro blanco principal de ESTE modal específico
    const $modalContext = $(this).closest('.bg-white');
    const $creationDiv = $modalContext.find('.js-inline-kb-creation');
    
    $creationDiv.toggleClass('hidden');
    if (!$creationDiv.hasClass('hidden')) {
        $modalContext.find('.js-inline-kb-name').focus();
    }
});

$(document).on('click', '.js-btn-save-inline-kb', function() {
    const $btn = $(this);
    const $modalContext = $btn.closest('.bg-white');
    const $input = $modalContext.find('.js-inline-kb-name');
    const $select = $modalContext.find('select'); // Encuentra el <select> de este modal
    const kbName = $input.val().trim();

    if (!kbName) return;

    $btn.text('...').prop('disabled', true);
    const token = localStorage.getItem('auth_token');

    $.ajax({
        url: '/api/v1/kbs',
        type: 'POST',
        contentType: 'application/json',
        headers: {
            'Authorization': 'Bearer ' + token
        },
        data: JSON.stringify({ name: kbName, description: "Creada automáticamente desde el selector" }),
        success: function(response) {
            const newId = response.kb_id || response.id || response.name;
            const newOption = new Option(response.name, newId, true, true);
            
            // Se inserta en el dropdown del modal abierto y se selecciona
            $select.append(newOption).trigger('change');
            
            // Limpieza
            $input.val('');
            $modalContext.find('.js-inline-kb-creation').addClass('hidden');
            
            if (typeof currentKBsData !== 'undefined') currentKBsData.push(response);
            if (window.showToast) window.showToast('Knowledge Base creada.', 'success');
        },
        error: function(err) {
            console.error("Error creando KB:", err);
            if (window.showToast) window.showToast('Error creando la KB.', 'error');
        },
        complete: function() {
            $btn.text('Crear').prop('disabled', false);
        }
    });
});
});

let taskIntervals = {};

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

    UI.updateDownloadsBadge();
}

// --- FUNCIÓN DE ACTUALIZACIÓN DINÁMICA ---
window.refreshUsageMetrics = function () {
    // 1. Obtener el token (como haces en el resto de la app)
    const token = localStorage.getItem('auth_token');

    // 2. PETICIÓN DE BYTES (Endpoint corregido: /api/v1/users/me)
    $.ajax({
        url: '/users/me',
        method: 'GET',
        headers: {
            'Authorization': 'Bearer ' + token
        },
        success: function (res) {
            // Verificamos la estructura: res.quota.used_bytes
            if (res && res.quota) {
                const used = res.quota.used_bytes;
                const limit = res.quota.limit_bytes;

                // Conversión a MB y GB
                const usedMB = (used / (1024 * 1024)).toFixed(1);
                const limitGB = (limit / (1024 * 1024 * 1024)).toFixed(0);

                // Cálculo de porcentaje (máximo 100%)
                const pct = Math.min((used / limit) * 100, 100);

                // Actualizar UI
                $('#usage-storage-text').text(`${usedMB} MB / ${limitGB} GB`);
                $('#usage-storage-bar').css('width', pct + '%');
                $('#usage-kb-count').text(res.kb_count || 0);
                $('#usage-doc-count').text(res.document_count || 0);


            }
        },
        error: function (err) {
            console.error("Error en el pedido de bytes:", err);
            $('#usage-storage-text').text("Error de conexión");
        }
    });

    const $list = $('#adapters-usage-list').empty();

    // 1. Buscamos qué fuentes existen (Discovery)
    $.ajax({
        url: '/api/v1/sources',
        method: 'GET',
        headers: { 'Authorization': 'Bearer ' + token },
        success: function (sources) {

            sources.forEach(source => {
                if (source.id === 'cache') return; // Saltamos la caché

                // Creamos la "caja" vacía para el adaptador
                const $item = $(`
                <div class="p-4 border border-slate-100 rounded-xl bg-white shadow-sm">
                    <div class="flex justify-between items-center mb-3">
                        <span class="font-bold text-xs text-slate-700 uppercase">${source.name}</span>
                        <span class="px-2 py-0.5 bg-blue-50 text-blue-600 text-[10px] font-bold rounded">SYSTEM POOL</span>
                    </div>
                    <div id="stats-${source.id}" class="text-xs space-y-2 text-slate-500">
                        <i class="fas fa-spinner fa-spin"></i> Sincronizando...
                    </div>
                </div>
            `).appendTo($list);

                // 2. Pedimos el estado real de esa fuente
                $.ajax({
                    url: `/api/v1/users/me/sources/${source.id}/config`,
                    method: 'GET',
                    headers: { 'Authorization': 'Bearer ' + token },
                    success: function (res) {
                        console.log(res);
                        if (res.state) {
                            const consumed = res.state.daily_system_search_count || 0;
                            const limit = res.state.total_system_search_count || 0;

                            // Actualizamos el contenido con el nombre arriba y stats abajo
                            $(`#stats-${source.id}`).html(`
                            <div class="flex justify-between items-center">
                                <span class="font-medium">Daily Searches:</span>
                                <span class="font-mono font-bold text-slate-800">${consumed} / ${limit}</span>
                            </div>
                        `);
                        }
                    }
                });
            });
        }
    });
};

function sanitizeAndValidateDoi(input) {
    let clean = input.trim().replace(/^(https?:\/\/)?(dx\.)?doi\.org\//i, '').replace(/^doi:\s*/i, '');
    return /^10\.\d{4,9}\/[-._;()/:a-zA-Z0-9]+$/i.test(clean) ? clean : null;
}