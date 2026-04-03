/**
 * Global API interceptor and configuration.
 *
 * Configures jQuery's AJAX defaults to dynamically route all relative endpoints
 * to the backend server, inject the authentication token, and handle global
 * unauthorized responses.
 */

const API_BASE_URL = 'http://localhost:8000/api/v1';

$.ajaxPrefilter(function(options, originalOptions, jqXHR) {
    if (!options.url.startsWith('http') && !options.url.includes('.html')) {
        const path = options.url.startsWith('/') ? options.url : '/' + options.url;
        options.url = API_BASE_URL + path;
    }
});

$(document).ready(function() {
    $.ajaxSetup({
        beforeSend: function(xhr) {
            const token = getAuthToken();
            if (token) {
                xhr.setRequestHeader('X-User-ID', token);
            }
        },
        error: function(jqXHR) {
            if (jqXHR.status === 401 || jqXHR.status === 403) {
                logoutUser();
            }
        }
    });
});

// ... (tu código anterior de $.ajaxPrefilter y $.ajaxSetup se mantiene igual)

/**
 * Global Toast Notification System
 */
window.showToast = function(message, type = 'success') {
    // Si el contenedor no existe, lo creamos dinámicamente
    if ($('#toast-container').length === 0) {
        $('body').append('<div id="toast-container" class="fixed bottom-5 right-5 z-[100] flex flex-col gap-2 pointer-events-none"></div>');
    }

    const bgColor = type === 'success' ? 'bg-slate-800' : 'bg-red-600';
    const icon = type === 'success' ? '✓' : '✕';

    const toast = $('<div>')
        .addClass(`flex items-center gap-3 px-4 py-3 rounded-lg shadow-xl text-white text-sm font-medium transform transition-all duration-300 translate-y-12 opacity-0 ${bgColor}`)
        .html(`<span class="flex-shrink-0 flex items-center justify-center w-5 h-5 rounded-full border border-white/30 text-xs">${icon}</span> ${message}`);

    $('#toast-container').append(toast);

    // Animación de entrada
    requestAnimationFrame(() => {
        toast.removeClass('translate-y-12 opacity-0');
    });

    // Auto-destrucción a los 3 segundos
    setTimeout(() => {
        toast.addClass('translate-y-12 opacity-0');
        setTimeout(() => toast.remove(), 300); // Espera a que termine la animación css
    }, 3000);
};