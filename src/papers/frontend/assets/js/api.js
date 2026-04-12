/**
 * Global API interceptor and configuration.
 *
 * Configures jQuery's AJAX defaults to dynamically route all relative endpoints
 * to the backend server, inject the authentication token, and handle global
 * unauthorized responses.
 */

const ENV_CONFIG = {
    development: {
        API_URL: 'http://127.0.0.1:8000/api/v1' 
    },
    production: {
        API_URL: '/api/v1' 
    }
};

const currentHostname = window.location.hostname;
const isDevelopment = currentHostname === 'localhost' || currentHostname === '127.0.0.1';

const API_BASE_URL = isDevelopment ? ENV_CONFIG.development.API_URL : ENV_CONFIG.production.API_URL;


$.ajaxPrefilter(function(options, originalOptions, jqXHR) {
    if (!options.url.startsWith('http') && !options.url.includes('.html')) {
        const path = options.url.startsWith('/') ? options.url : '/' + options.url;
        
        if (path.startsWith('/api/v1')) {
            const baseUrl = API_BASE_URL.replace('/api/v1', '');
            options.url = baseUrl + path;
        } else {
            options.url = API_BASE_URL + path;
        }
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


/**
 * Global Toast Notification System
 */
window.showToast = function(message, type = 'success') {
    if ($('#toast-container').length === 0) {
        $('body').append('<div id="toast-container" class="fixed bottom-5 right-5 z-[100] flex flex-col gap-2 pointer-events-none"></div>');
    }

    const bgColor = type === 'success' ? 'bg-slate-800' : 'bg-red-600';
    const icon = type === 'success' ? '✓' : '✕';

    const toast = $('<div>')
        .addClass(`flex items-center gap-3 px-4 py-3 rounded-lg shadow-xl text-white text-sm font-medium transform transition-all duration-300 translate-y-12 opacity-0 ${bgColor}`)
        .html(`<span class="flex-shrink-0 flex items-center justify-center w-5 h-5 rounded-full border border-white/30 text-xs">${icon}</span> ${message}`);

    $('#toast-container').append(toast);

    requestAnimationFrame(() => {
        toast.removeClass('translate-y-12 opacity-0');
    });

    setTimeout(() => {
        toast.addClass('translate-y-12 opacity-0');
        setTimeout(() => toast.remove(), 300); 
    }, 3000);
};