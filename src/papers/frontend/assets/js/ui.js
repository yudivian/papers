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
        });
    }
};