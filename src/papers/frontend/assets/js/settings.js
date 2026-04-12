/**
 * Server-Driven UI engine for adapter configurations.
 * * Dynamically fetches JSON schemas from the backend and generates 
 * HTML forms. Adapters with no configurable properties are hidden.
 */

function loadSettingsPanel() {
    // 1. Elevamos Settings por encima de Downloads temporalmente
    $('#settingsPanel').css('z-index', 65);
    $('#downloadsPanel').css('z-index', 60);

    // 2. Exclusión mutua (animación)
    $('#downloadsPanel').addClass('translate-x-full');
    $('#settingsPanel').removeClass('translate-x-full');

    fetchAdapters();
}

function closeSettingsPanel() {
    $('#settingsPanel').addClass('translate-x-full');
}

function fetchAdapters() {
    const container = $('#adapterTabs');
    const formContainer = $('#dynamicFormContainer');

    container.html('<p class="text-xs text-slate-500 text-center mt-4">Loading...</p>');
    formContainer.empty();

    // 1. Get the list of all sources
    $.get('/sources').done(function (sources) {

        // 2. Prepare to fetch the schema for each source
        const schemaPromises = sources.map(source => {
            return $.get(`/sources/${source.id}/schema`).then(schema => {
                return { source: source, schema: schema };
            }).catch(() => {
                // Ignore sources that fail to return a schema
                return { source: source, schema: null };
            });
        });

        // 3. Wait for all schemas to arrive
        $.when.apply($, schemaPromises).done(function () {
            // Convert arguments to an array
            const results = Array.prototype.slice.call(arguments);
            container.empty();
            let firstRenderedId = null;

            results.forEach(result => {
                // If the schema has properties, it requires configuration
                if (result.schema && result.schema.properties && Object.keys(result.schema.properties).length > 0) {

                    const btn = $('<button>')
                        .text(result.source.name)
                        .addClass('w-full text-left px-4 py-2 text-sm font-medium rounded-lg hover:bg-slate-100 transition-colors')
                        .on('click', function () {
                            // Highlight active tab
                            $('#adapterTabs button').removeClass('bg-blue-50 text-blue-700');
                            $(this).addClass('bg-blue-50 text-blue-700');
                            renderAdapterForm(result.source.id, result.schema);
                        });

                    container.append(btn);

                    // Auto-load the first valid tab
                    if (!firstRenderedId) {
                        firstRenderedId = result.source.id;
                        btn.addClass('bg-blue-50 text-blue-700');
                        renderAdapterForm(firstRenderedId, result.schema);
                    }
                }
            });

            if (!firstRenderedId) {
                container.html('<p class="text-xs text-slate-500 text-center mt-4">No configurable adapters found.</p>');
                formContainer.html('<div class="flex h-full items-center justify-center text-slate-400"><p>System is fully autonomous.</p></div>');
            }

            const orcidBtn = $('<button>')
                .text('ORCID')
                .addClass('w-full text-left px-4 py-2 text-sm font-medium rounded-lg hover:bg-slate-100 transition-colors')
                .on('click', function () {
                    // Highlight active tab
                    $('#adapterTabs button').removeClass('bg-blue-50 text-blue-700');
                    $(this).addClass('bg-blue-50 text-blue-700');
                    renderOrcidForm();
                });

            container.append(orcidBtn);
        });
    });
}

function renderAdapterForm(sourceId, schema) {
    const container = $(`#adapter-config-${sourceId}`);
    const formContainer = $('#dynamicFormContainer');

    $.get(`/api/v1/users/me/sources/${sourceId}/config`, {
        headers: { 'Authorization': 'Bearer ' + localStorage.getItem('auth_token') }
    }).done(function (config) {
        formContainer.empty();
        
        const $header = $('<div class="flex flex-wrap gap-4 mb-6 pb-4 border-b border-slate-100"></div>');
        const $form = $('<form id="adapterConfigForm" class="space-y-6"></form>');
        
        Object.keys(schema.properties).forEach(key => {
            const prop = schema.properties[key];
            const value = config[key] !== undefined ? config[key] : (prop.default !== undefined ? prop.default : '');

            if (prop.readOnly === true) {
                let badgeClass = 'bg-slate-100 text-slate-600';
                let text = value;

                if (prop.type === 'boolean') {
                    if (key === 'is_key_invalid') {
                        badgeClass = value ? 'bg-red-100 text-red-800' : 'bg-blue-100 text-blue-800';
                        text = value ? '⚠️ Invalid' : 'Healthy';
                    } else {
                        badgeClass = value ? 'bg-green-100 text-green-800' : 'bg-slate-100 text-slate-500';
                        text = value ? 'Active' : 'Inactive';
                    }
                }
                $header.append(`
                    <div class="flex flex-col">
                        <span class="text-xs font-bold text-slate-400 uppercase tracking-tight">${prop.title || key}</span>
                        <span class="px-3 py-1 rounded-full text-xs font-bold uppercase ${badgeClass}">${text}</span>
                    </div>
                `);
                return; 
            }

            const $fieldDiv = $('<div>').addClass('flex flex-col gap-2');
            const labelHtml = `<label class="text-xs font-bold text-slate-500 uppercase">${prop.title || key}</label>`;
            
            if (prop.type === 'boolean') {
                const checked = value ? 'checked' : '';
                const controls = prop.json_schema_extra?.ui_controls ? JSON.stringify(prop.json_schema_extra.ui_controls) : '';
                
                $fieldDiv.html(`
                    <div class="flex items-center justify-between">
                        <span class="text-sm font-medium text-slate-700">${prop.description || prop.title}</span>
                        <label class="relative inline-flex items-center cursor-pointer">
                            <input type="checkbox" name="${key}" class="sr-only peer adapter-input ui-toggle" data-controls='${controls}' ${checked}>
                            <div class="w-9 h-5 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-indigo-600"></div>
                        </label>
                    </div>
                `);
            } else {
                const isPassword = prop.json_schema_extra?.ui_widget === 'password' || key.includes('key');
                $fieldDiv.append(`
                    ${labelHtml}
                    <input type="${isPassword ? 'password' : 'text'}" name="${key}" value="${value}" 
                           class="w-full px-3 py-2 text-sm border border-slate-200 rounded-md focus:ring-1 focus:ring-indigo-500 outline-none adapter-input transition-all">
                    ${prop.description ? `<p class="text-xs text-slate-400 mt-1">${prop.description}</p>` : ''}
                `);
            }
            $form.append($fieldDiv);
        });

        const $saveBtn = $('<button>')
            .attr('type', 'button')
            .addClass('w-full mt-6 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-bold rounded-lg shadow-sm transition-colors')
            .text('Save Configuration')
            .on('click', function(e) {
                e.preventDefault();
                const btn = $(this);
                const originalText = btn.text();
                btn.text('Saving...').prop('disabled', true).addClass('opacity-70');
                
                // Llamamos a la función huérfana
                saveAdapterConfig(sourceId, $form, schema);
                
                // Restauramos el botón después de 1 segundo para feedback visual
                setTimeout(() => {
                    btn.text(originalText).prop('disabled', false).removeClass('opacity-70');
                }, 1000);
            });
        
        $form.append($saveBtn);

        if ($header.children().length > 0) formContainer.append($header);
        formContainer.append($form);

        $form.find('.ui-toggle').each(function() {
            const $toggle = $(this);
            const controlsData = $toggle.attr('data-controls');
            if (!controlsData) return;
            
            let targets = [];
            try { targets = JSON.parse(controlsData); } catch(e) {}
            
            const update = () => {
                const isEnabled = $toggle.is(':checked');
                targets.forEach(targetName => {
                    const $target = $form.find(`[name="${targetName}"]`);
                    $target.prop('disabled', !isEnabled);
                    $target.toggleClass('bg-slate-50 opacity-60 cursor-not-allowed', !isEnabled);
                });
            };
            $toggle.on('change', update);
            update(); 
        });
    });
}


function saveAdapterConfig(sourceId, formElement, schema) {
    const formData = {};

    formElement.find('input').each(function () {
        if (this.type === 'checkbox') {
            formData[this.name] = this.checked;
        } else if (this.value.trim() !== '') {
            formData[this.name] = this.value.trim();
        }
    });

    $.ajax({
        url: `/api/v1/users/me/sources/${sourceId}/config`,
        type: 'PUT',
        headers: { 'Authorization': 'Bearer ' + localStorage.getItem('auth_token') },
        contentType: 'application/json',
        data: JSON.stringify(formData),
        success: function () {
            window.showToast('Configuration saved successfully!', 'success');
            renderAdapterForm(sourceId, schema);
        },
        error: function (err) {
            window.showToast('Failed to save configuration. Check inputs.', 'error');
            console.error(err);
        }
    });
}
$(document).ready(function () {
    $(document).on('click', '#openSettingsBtn', loadSettingsPanel);
    $(document).on('click', '#closeSettingsBtn', closeSettingsPanel);
});


/**
 * Renders the ORCID configuration form in the settings panel.
 * Strictly follows the visual style, order, and structure of dynamic adapter forms
 * (e.g., Core, OpenAlex) generated by renderAdapterForm(), using indigo colors.
 */
function renderOrcidForm() {
    const formContainer = $('#dynamicFormContainer');
    formContainer.html('<p class="text-xs text-slate-500 text-center mt-4">Loading settings for ORCID Integration...</p>');

    $.ajax({
        url: '/api/v1/orcid/settings',
        type: 'GET',
        success: function (currentConfig) {
            formContainer.empty();
            const $form = $('<form id="orcidConfigForm" class="space-y-4"></form>');

            // 1. ORCID iD (String Input) - AHORA VA PRIMERO
            const $inputWrapper = $('<div class="flex flex-col gap-2"></div>');
            $inputWrapper.append('<label class="text-xs font-bold text-slate-500 uppercase">Orcid Id</label>');
            
            
            // Tailwind classes to look exactly like dynamic inputs, with indigo focus
            const inputDisabledState = currentConfig.is_enabled ? '' : 'disabled';
            $inputWrapper.append(`
                <input type="text" name="orcid_id" id="orcidIdInput" value="${currentConfig.orcid_id || ''}" 
                       class="w-full px-3 py-2 text-sm border border-slate-200 rounded-md focus:ring-1 focus:ring-indigo-500 outline-none orcid-input transition-all disabled:bg-slate-100 disabled:text-slate-400 disabled:cursor-not-allowed" 
                       data-type="string" ${inputDisabledState}>
            `);
            $inputWrapper.append('<p class="text-xs text-slate-400 mb-1">Your 16-digit ORCID identifier (e.g. 0000-0000-0000-0000).</p>');
            $form.append($inputWrapper);

            // 2. Enable Sync (Boolean Toggle) - AHORA VA DEBAJO
            const $toggleWrapper = $('<div class="flex items-center justify-between"><div class="flex flex-col gap-2"></div></div>'); 
            $toggleWrapper.append('<span class="text-sm font-medium text-slate-700">Activate synchronization with your ORCID profile.</span>');
            
            const isChecked = currentConfig.is_enabled ? 'checked' : '';
            $toggleWrapper.append(`
                <label class="relative inline-flex items-center cursor-pointer mt-1">
                    <input type="checkbox" name="is_enabled" id="orcidToggle" class="sr-only peer orcid-input" data-type="boolean" ${isChecked}>
                    <div class="w-9 h-5 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-indigo-600"></div>
                </label>
            `);
            $form.append($toggleWrapper);

            // Event Listener for Toggle -> Input Disabled state
            $form.find('#orcidToggle').on('change', function() {
                const isEnabled = $(this).is(':checked');
                $form.find('#orcidIdInput').prop('disabled', !isEnabled);
            });

            // 3. Save Button (Exact clone, indigo color, no shadow)
            const $saveBtn = $('<button>')
                .attr('type', 'button')
                .addClass('w-full mt-4 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-bold rounded-lg transition-colors')
                .text('Save Configuration')
                .on('click', function(e) {
                    e.preventDefault();
                    const btn = $(this);
                    const originalText = btn.text();
                    
                    const payload = {
                        is_enabled: $form.find('input[name="is_enabled"]').is(':checked'),
                        orcid_id: $form.find('input[name="orcid_id"]').val().trim()
                    };

                    // Client-side validation
                    if (payload.is_enabled) {
                        if (!payload.orcid_id) {
                            if (window.showToast) window.showToast('Orcid Id is required when enabled.', 'error');
                            return;
                        }

                        const orcidRegex = /^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$/i;
                        if (!orcidRegex.test(payload.orcid_id)) {
                            if (window.showToast) window.showToast('Invalid ORCID format. Use XXXX-XXXX-XXXX-XXXX.', 'error');
                            return;
                        }
                    }

                    btn.text('Saving...').prop('disabled', true).addClass('opacity-70');

                    $.ajax({
                        url: '/api/v1/orcid/settings',
                        type: 'POST',
                        contentType: 'application/json',
                        data: JSON.stringify(payload),
                        success: function (res) {
                            if (window.showToast) window.showToast('Settings saved successfully', 'success');
                            
                            // Dynamic UI update for sidebar
                            if (payload.is_enabled && payload.orcid_id) {
                                $('#navOrcidProfile').removeClass('hidden');
                            } else {
                                $('#navOrcidProfile').addClass('hidden');
                            }
                        },
                        error: function (err) {
                            const errorMsg = err.responseJSON && err.responseJSON.detail 
                                ? err.responseJSON.detail 
                                : 'Failed to save settings';
                            if (window.showToast) window.showToast(errorMsg, 'error');
                            console.error("Save error:", err);
                        },
                        complete: function () {
                            setTimeout(() => {
                                btn.text(originalText).prop('disabled', false).removeClass('opacity-70');
                            }, 500);
                        }
                    });
                });
            
            $form.append($saveBtn);
            formContainer.append($form);
        },
        error: function () {
            formContainer.html('<p class="text-xs text-red-500 text-center mt-4">Failed to load current configuration for ORCID Integration.</p>');
        }
    });
}