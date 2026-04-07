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