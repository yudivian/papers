/**
 * Workspace Controller
 * Handles the display, creation, and deletion of Knowledge Bases.
 */

let confirmActionCallback = null;

$(document).ready(function() {
    // 1. Initial Load
    loadKBs();

    // 2. KB Modal interactions
    $('#btnNewKB').on('click', openModal);
    $('#btnCloseModal, #btnCancelModal').on('click', closeModal);
    
    // 3. Form submission
    // 3. Form submission and Create buttons
    $('#btnCreateStay').on('click', function(e) {
        if ($('#formNewKB')[0].checkValidity()) {
            e.preventDefault();
            createKB(false); // false = no entrar
        } else {
            $('#formNewKB')[0].reportValidity();
        }
    });

    $('#formNewKB').on('submit', function(e) {
        e.preventDefault(); // El botón "Create & Enter" (type=submit) activa esto
        createKB(true); // true = entrar automáticamente
    });

    // 4. View switching
    $('#btnBackToGrid').on('click', showGrid);

    // 5. Confirm Modal bindings
    $('#btnCancelConfirm').on('click', closeConfirmModal);
    $('#btnAcceptConfirm').on('click', function() {
        if (confirmActionCallback) confirmActionCallback();
        closeConfirmModal();
    });

    // Mobile Sidebar toggle
    $(document).on('click', '#openSidebarMobileBtn', function() {
        $('#mobileSidebarOverlay').removeClass('hidden');
        setTimeout(() => {
            $('#mobileSidebarOverlay').removeClass('opacity-0').addClass('opacity-100');
            $('#mainSidebar').removeClass('-translate-x-full');
        }, 10);
    });

    // (Debajo de los listeners que ya tienes)
    $('#btnCloseEditModal, #btnCancelEditModal').on('click', closeEditModal);
    $('#formEditKB').on('submit', function(e) {
        e.preventDefault();
        executeEdit();
    });
});

function loadKBs() {
    const grid = $('#workspace-grid');
    grid.html('<p class="text-slate-500 col-span-full text-center py-10">Loading knowledge bases...</p>');

    $.get('/kbs').done(function(kbs) {
        grid.empty();
        
        if (kbs.length === 0) {
            grid.html(`
                <div class="col-span-full bg-white border border-slate-200 border-dashed rounded-xl p-12 text-center">
                    <p class="text-slate-500 mb-4">You don't have any Knowledge Bases yet.</p>
                    <button onclick="openModal()" class="text-blue-600 font-medium hover:underline">Create your first project</button>
                </div>
            `);
            return;
        }

        kbs.forEach(kb => {
            const docCount = kb.document_ids ? kb.document_ids.length : 0;
            
            const card = $(`
                <div class="relative bg-white border border-slate-200 rounded-xl p-6 hover:shadow-md hover:border-blue-300 transition-all cursor-pointer group flex flex-col h-full">
                    <div class="absolute top-3 right-3 flex gap-1 opacity-0 group-hover:opacity-100 transition-all">
                        <button class="btn-edit-card text-slate-400 hover:text-blue-600 hover:bg-blue-50 p-2 rounded-lg transition-colors" title="Edit Project">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path></svg>
                        </button>
                        <button class="btn-delete-card text-slate-400 hover:text-red-500 hover:bg-red-50 p-2 rounded-lg transition-colors" title="Delete Project">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                        </button>
                    </div>
                    
                    <div class="flex-1 pr-14">
                        <h3 class="text-lg font-bold text-slate-800 group-hover:text-blue-600 transition-colors line-clamp-1">${kb.name}</h3>
                        <p class="text-sm text-slate-500 mt-2 line-clamp-2">${kb.description || 'No description provided.'}</p>
                    </div>
                    <div class="mt-6 pt-4 border-t border-slate-50 flex justify-between items-center">
                        <span class="text-xs font-semibold px-2 py-1 bg-blue-50 text-blue-700 rounded-md">
                            ${docCount} Documents
                        </span>
                        <span class="text-slate-400 text-lg opacity-0 group-hover:opacity-100 transition-opacity">→</span>
                    </div>
                </div>
            `);
            
            card.on('click', () => showDetail(kb));
            
            card.find('.btn-edit-card').on('click', function(e) {
                e.stopPropagation(); 
                openEditModal(kb);
            });

            card.find('.btn-delete-card').on('click', function(e) {
                e.stopPropagation(); 
                requestDeleteKB(kb);
            });

            grid.append(card);
        });
    }).fail(function() {
        grid.html('<div class="col-span-full p-8 text-center bg-red-50 border border-red-100 rounded-xl text-red-600">Error loading projects. Check if the backend is running.</div>');
    });
}


function createKB(enterAfterCreation) {
    const name = $('#kbName').val().trim();
    const desc = $('#kbDesc').val().trim();

    $.ajax({
        url: '/kbs',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ name: name, description: desc }),
        success: function(response) {
            closeModal();
            window.showToast(`Project "${name}" created.`, 'success');
            
            if (enterAfterCreation) {
                loadKBs(); 
                showDetail({
                    id: response.kb_id || name, 
                    name: name,
                    description: desc,
                    document_ids: []
                });
            } else {
                loadKBs();
            }
        },
        error: function(err) {
            window.showToast('Error creating project.', 'error');
            console.error(err);
        }
    });
}

function requestDeleteKB(kb) {
    const targetId = kb.id || kb.kb_id || kb.name; 

    if (!targetId) {
        window.showToast('Error: Could not identify the Knowledge Base ID.', 'error');
        return;
    }

    openConfirmModal(
        'Delete Knowledge Base',
        `Are you sure you want to delete the project <br><b class="text-slate-800">"${kb.name}"</b>?<br><br>Documents inside will remain safely on your disk.`,
        function() {
            executeDelete(targetId);
        }
    );
}

function executeDelete(kbId) {
    $.ajax({
        url: `/kbs/${kbId}`,
        type: 'DELETE',
        success: function() {
            window.showToast('Project deleted successfully.', 'success');
            showGrid(); 
            loadKBs();  
        },
        error: function(err) {
            window.showToast('Failed to delete project.', 'error');
            console.error(err);
        }
    });
}

// --- View Logic ---

function showDetail(kb) {
    $('#workspace-grid').addClass('hidden');
    $('#workspace-detail').removeClass('hidden');

    $('#detailTitle').text(kb.name);
    $('#detailDesc').text(kb.description || 'No description provided.');
    
    // Bind delete button from inside the detail view
    $('#btnDeleteKB').off('click').on('click', () => requestDeleteKB(kb));
    $('#btnEditKB').off('click').on('click', () => openEditModal(kb));

    const list = $('#detailDocsList');
    list.empty();

    if (!kb.document_ids || kb.document_ids.length === 0) {
        list.append('<li class="text-sm text-slate-500 italic">This project is empty. Add documents via Ingestion.</li>');
    } else {
        kb.document_ids.forEach(doi => {
            list.append(`
                <li class="bg-white border border-slate-100 px-4 py-3 rounded text-sm text-slate-700 font-mono shadow-sm">
                    ${doi}
                </li>
            `);
        });
    }
}

function showGrid() {
    $('#workspace-detail').addClass('hidden');
    $('#workspace-grid').removeClass('hidden');
}

// --- Modals Logic ---

function openModal() {
    $('#kbName').val('');
    $('#kbDesc').val('');
    $('#modalNewKB').removeClass('hidden');
    setTimeout(() => { $('#modalNewKB > div').removeClass('scale-95').addClass('scale-100'); }, 10);
}

function closeModal() {
    $('#modalNewKB > div').removeClass('scale-100').addClass('scale-95');
    setTimeout(() => { $('#modalNewKB').addClass('hidden'); }, 150);
}

function openConfirmModal(title, message, onConfirm) {
    $('#confirmTitle').text(title);
    $('#confirmMessage').html(message);
    confirmActionCallback = onConfirm;

    $('#modalConfirm').removeClass('hidden');
    setTimeout(() => { $('#modalConfirm > div').removeClass('scale-95').addClass('scale-100'); }, 10);
}

function closeConfirmModal() {
    $('#modalConfirm > div').removeClass('scale-100').addClass('scale-95');
    setTimeout(() => { 
        $('#modalConfirm').addClass('hidden'); 
        confirmActionCallback = null;
    }, 150);
}

// --- Edit Logic ---

function openEditModal(kb) {
    if (!kb) return;

    // Llenar el formulario
    $('#editKbId').val(kb.id || kb.kb_id || kb.name);
    $('#editKbName').val(kb.name);
    $('#editKbDesc').val(kb.description || '');

    // Quitamos el '.css('display', 'flex')' que causaba el bug. 
    // Solo removemos la clase hidden.
    $('#modalEditKB').removeClass('hidden'); 
    
    // Animación de entrada
    setTimeout(() => { 
        $('#modalEditKB > div').removeClass('scale-95').addClass('scale-100'); 
    }, 10);
}

function closeEditModal() {
    $('#modalEditKB > div').removeClass('scale-100').addClass('scale-95');
    
    setTimeout(() => { 
        // Agregamos hidden y, por si acaso quedó algún residuo, borramos el atributo style
        $('#modalEditKB').addClass('hidden').css('display', ''); 
    }, 150);
}

function closeEditModal() {
    $('#modalEditKB > div').removeClass('scale-100').addClass('scale-95');
    setTimeout(() => { $('#modalEditKB').addClass('hidden'); }, 150);
}

function executeEdit() {
    const kbId = $('#editKbId').val();
    const newName = $('#editKbName').val().trim();
    const newDesc = $('#editKbDesc').val().trim();

    if (!newName) {
        if (window.showToast) window.showToast('Project name is required.', 'error');
        return;
    }

    $.ajax({
        url: `/kbs/${kbId}`,
        type: 'PATCH', 
        contentType: 'application/json',
        data: JSON.stringify({ name: newName, description: newDesc }),
        success: function(updatedKb) {
            closeEditModal();
            if (window.showToast) window.showToast('Project updated successfully.', 'success');
            
            // Si estamos en la vista de detalle, actualizamos los textos
            if (!$('#workspace-detail').hasClass('hidden')) {
                $('#detailTitle').text(updatedKb.name);
                $('#detailDesc').text(updatedKb.description || 'No description provided.');
                
                // Actualizamos los botones del detalle con el nuevo objeto
                $('#btnEditKB').off('click').on('click', () => openEditModal(updatedKb));
                $('#btnDeleteKB').off('click').on('click', () => requestDeleteKB(updatedKb));
            }

            loadKBs(); // Refresca el grid
        },
        error: function(err) {
            if (window.showToast) window.showToast('Failed to update project. Check backend logs.', 'error');
            console.error("Error updating KB:", err);
        }
    });
}