/**
 * Authentication management module.
 */

const TOKEN_KEY = 'papers_user_session';

function requireAuth() {
    if (!localStorage.getItem(TOKEN_KEY)) {
        window.location.replace('/login.html');
    }
}

function getAuthToken() {
    return localStorage.getItem(TOKEN_KEY);
}

// Vinculamos el evento submit directamente al formulario para evitar que la página se recargue
$(document).ready(function () {
    // Asegúrate de que tu formulario en login.html tenga id="loginForm"
    $('#loginForm').on('submit', function (e) {
        e.preventDefault(); // <-- Esto detiene la recarga fantasma del navegador

        const userId = $('#userId').val().trim();
        const password = $('#password').val().trim();
        const $btn = $(this).find('button[type="submit"]');

        $btn.prop('disabled', true).text('Autenticando...');

        // Usamos $.ajax para que el interceptor en api.js le ponga la URL base correcta
        // $.ajax({
        //     url: '/auth/login', 
        //     type: 'POST',
        //     contentType: 'application/json',
        //     data: JSON.stringify({
        //         user_id: userId,
        //         password: password
        //     }),
        //     success: function() {
        //         // Guardamos la identidad para la sesión y para el interceptor de api.js
        //         localStorage.setItem(TOKEN_KEY, userId);
        //         localStorage.setItem('userId', userId);

        //         window.location.replace('/index.html');
        //     },
        //     error: function(err) {
        //         console.error("Error en login:", err);
        //         alert("Acceso denegado. Revisa tus credenciales.");
        //         $btn.prop('disabled', false).text('Entrar');
        //     }
        // });
        $.ajax({
            url: '/auth/login',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                user_id: userId,
                password: password
            }),
            // MODIFICATION HERE: Add 'response' parameter to capture the backend data
            success: function (response) {
                const backendToken = response.access_token || response.token || userId;
                localStorage.setItem(TOKEN_KEY, backendToken);

                const cleanId = response.user_id || userId;
                localStorage.setItem('userId', cleanId);

                window.location.replace('/index.html');
            },
            error: function (err) {
                console.error("Error en login:", err);
                alert("Acceso denegado. Revisa tus credenciales.");
                $btn.prop('disabled', false).text('Entrar');
            }
        });
    });
});

function logoutUser() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem('userId');
    window.location.replace('/login.html');
}

function redirectIfAuthenticated() {
    if (localStorage.getItem(TOKEN_KEY)) {
        window.location.replace('/index.html');
    }
}