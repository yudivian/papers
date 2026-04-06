/**
 * Frontend Utilities
 */

const UIUtils = {
    /**
     * Filters an array of objects by verifying that ALL search terms 
     * exist within the target text, regardless of order (Tokenized search).
     *
     * @param {Array} items - The array of objects to filter (e.g., documents, projects).
     * @param {string} query - The text entered by the user in the search bar.
     * @param {Function} textExtractor - Callback that receives an item and returns the string to be searched.
     * @returns {Array} - The filtered array.
     */
    filterByTerms: function(items, query, textExtractor) {
        if (!items || !Array.isArray(items)) return [];
        if (!query || typeof query !== 'string') return items;

        const terms = query.toLowerCase().split(/\s+/).filter(word => word.length > 0);
        if (terms.length === 0) return items;

        return items.filter(item => {
            const targetText = (textExtractor(item) || '').toLowerCase();
            return terms.every(term => targetText.includes(term));
        });
    }
};