/**
 * Authentication management module.
 *
 * Handles user session state via browser local storage and controls access
 * to protected routes by enforcing authentication requirements.
 */

const TOKEN_KEY = 'papers_user_session';

function requireAuth() {
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) {
        window.location.replace('/login.html');
    }
}

function getAuthToken() {
    return localStorage.getItem(TOKEN_KEY);
}

async function loginUser(userId, password) {
    // 1. Apuntamos EXPLÍCITAMENTE al puerto 8000 de FastAPI
    try {
        await fetch('http://localhost:8000/api/v1/auth/login', {
            method: 'POST',
            headers: {
                'X-User-ID': userId,
                'Content-Type': 'application/json'
            }
        });
    } catch (e) {
        console.error("Error de red contactando al backend:", e);
    }

    // 2. Guardamos la identidad y redirigimos al Workspace
    localStorage.setItem(TOKEN_KEY, userId);
    window.location.href = '/index.html';
}

function logoutUser() {
    localStorage.removeItem(TOKEN_KEY);
    window.location.replace('/login.html');
}

function redirectIfAuthenticated() {
    const token = localStorage.getItem(TOKEN_KEY);
    if (token) {
        window.location.replace('/index.html');
    }
}