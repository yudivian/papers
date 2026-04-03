/**
 * Server-Driven UI engine for adapter configurations.
 * * Dynamically fetches JSON schemas from the backend and generates 
 * HTML forms. Adapters with no configurable properties are hidden.
 */

function loadSettingsPanel() {
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
    $.get('/sources').done(function(sources) {
        
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
        $.when.apply($, schemaPromises).done(function() {
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
                        .on('click', function() {
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

function renderAdapterForm(sourceId, preloadedSchema) {
    const formContainer = $('#dynamicFormContainer');
    formContainer.html('<p class="text-slate-500 text-sm">Loading user data...</p>');

    // We already have the schema, just fetch the user's saved values
    $.get(`/users/me/sources/${sourceId}/config`).done(function(config) {
        formContainer.empty();
        
        // Header info based on adapter status
        if (config.hasOwnProperty('personal_key_active')) {
            const statusColor = config.personal_key_active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800';
            const statusText = config.personal_key_active ? 'Active' : 'Exhausted/Invalid';
            const searches = config.daily_system_search_count !== undefined ? config.daily_system_search_count : 0;
            
            const statusBadge = `
                <div class="mb-6 p-4 rounded-lg bg-slate-50 border border-slate-100">
                    <div class="flex items-center justify-between mb-2">
                        <span class="text-xs font-medium text-slate-500 uppercase">Key Status</span>
                        <span class="text-xs font-semibold px-2 py-1 rounded ${statusColor}">${statusText}</span>
                    </div>
                    <div class="flex items-center justify-between">
                        <span class="text-xs font-medium text-slate-500 uppercase">System Searches Today</span>
                        <span class="text-sm font-semibold text-slate-700">${searches}</span>
                    </div>
                </div>
            `;
            formContainer.append(statusBadge);
        }

        const form = $('<form>').addClass('space-y-4').on('submit', function(e) {
            e.preventDefault();
            saveAdapterConfig(sourceId, form, preloadedSchema);
        });

        Object.keys(preloadedSchema.properties).forEach(key => {
            const prop = preloadedSchema.properties[key];
            const inputType = (prop.json_schema_extra && prop.json_schema_extra.ui_widget === 'password') ? 'password' : 'text';
            const currentValue = config[key] || '';

            const fieldDiv = $('<div>');
            const label = $('<label>').text(prop.title || key).addClass('block text-sm font-medium text-slate-700 mb-1');
            const input = $('<input>')
                .attr('type', inputType)
                .attr('name', key)
                .val(currentValue)
                .addClass('w-full px-3 py-2 border border-slate-300 rounded-md text-sm outline-none focus:ring-2 focus:ring-blue-500');
            
            if (prop.description) {
                const helpText = $('<p>').text(prop.description).addClass('text-xs text-slate-500 mt-1');
                fieldDiv.append(label, input, helpText);
            } else {
                fieldDiv.append(label, input);
            }

            form.append(fieldDiv);
        });

        const submitBtn = $('<button>')
            .attr('type', 'submit')
            .text('Save Configuration')
            .addClass('mt-4 w-full bg-slate-800 text-white text-sm font-medium py-2 rounded-md hover:bg-slate-900 transition-colors');
        
        form.append(submitBtn);
        formContainer.append(form);
    }).fail(function() {
        formContainer.html('<p class="text-red-500 text-sm">Failed to load user configuration.</p>');
    });
}

function saveAdapterConfig(sourceId, formElement, schema) {
    const formData = {};
    formElement.serializeArray().forEach(item => {
        if (item.value.trim() !== '') {
            formData[item.name] = item.value.trim();
        }
    });

   $.ajax({
        url: `/users/me/sources/${sourceId}/config`,
        type: 'PUT',
        contentType: 'application/json',
        data: JSON.stringify(formData),
        success: function() {
            window.showToast('Configuration saved successfully!', 'success');
            renderAdapterForm(sourceId, schema);
        },
        error: function(err) {
            window.showToast('Failed to save configuration. Check inputs.', 'error');
            console.error(err);
        }
    });
}

$(document).ready(function() {
    $(document).on('click', '#openSettingsBtn', loadSettingsPanel);
    $(document).on('click', '#closeSettingsBtn', closeSettingsPanel);
});