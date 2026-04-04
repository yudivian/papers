/**
 * UI Utilities and Shared Components Logic
 */

const UI = {
    /**
     * Loads the sidebar and automatically highlights the active link
     * based on the current URL.
     */
    loadSidebar: function() {
        $('#sidebar-container').load('/components/sidebar.html', function() {
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
        });
    },
    loadDownloadsPanel: function() {
        $.get('/components/downloads_panel.html', function(html) {
            $('body').append(html);
        });
    },

    // Actualiza el número de tareas activas
    updateDownloadsBadge: function() {
        let activeCount = $('#taskList .animate-pulse').length;
        if (activeCount > 0) {
            $('#downloadsBadge').text(activeCount).removeClass('hidden');
        } else {
            $('#downloadsBadge').addClass('hidden');
        }
    }
};

$(document).ready(function() {
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

    // Eventos delegados para abrir/cerrar el panel deslizante (Sin bloqueo)
    // Eventos delegados para abrir/cerrar el panel deslizante (Sin bloqueo)
    $(document).on('click', '#openDownloadsBtn', function() {
        // 1. Elevamos Downloads por encima de Settings temporalmente
        $('#downloadsPanel').css('z-index', 65);
        $('#settingsPanel').css('z-index', 60);

        // 2. Exclusión mutua (animación)
        $('#settingsPanel').addClass('translate-x-full');
        $('#downloadsPanel').removeClass('translate-x-full');
    });

    $(document).on('click', '#closeDownloadsBtn, #downloads-backdrop', function() {
        $('#downloads-backdrop').addClass('hidden');
        $('#downloadsPanel').addClass('translate-x-full');
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