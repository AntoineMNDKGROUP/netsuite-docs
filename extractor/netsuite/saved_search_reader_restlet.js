/**
 * @NApiVersion 2.1
 * @NScriptType Restlet
 * @NModuleScope SameAccount
 *
 * Documentation Hub - Saved Search Reader
 *
 * Expose deux endpoints via GET :
 *
 *   ?action=list&offset=0&limit=1000
 *     → liste paginée des saved searches accessibles à l'user (champs : internalid,
 *       scriptid, title, recordtype, owner, is_inactive, description, datecreated,
 *       datemodified). Pagine par 1000.
 *
 *   ?action=get&id=<internalid|scriptid>
 *     → définition complète d'une saved search :
 *         { internalid, scriptid, title, recordtype, is_public, filter_expression,
 *           filters: [...], columns: [...] }
 *       Chaque filter/column conserve : name, join, operator/summary, values,
 *       formula, label, sort, etc.
 *
 * IMPORTANT : on retourne JSON.stringify(...) — sur ce compte NetSuite, le framework
 * refuse un objet brut et fail en UNEXPECTED_ERROR sinon (cf. file_reader_restlet.js).
 *
 * En cas d'erreur applicative, renvoie { error: "...", action: "..." } avec HTTP 200
 * (l'appelant doit checker le champ `error` pour distinguer un succès partiel d'un
 * échec). Les exceptions Python du client sont déjà gérées côté requests.
 */
define(['N/search', 'N/runtime', 'N/error'], function (search, runtime, error) {

    /* ------------------------------------------------------------------------ */
    /*  list                                                                    */
    /* ------------------------------------------------------------------------ */

    function _buildLastmodFilter(sinceStr) {
        // Filtre robuste sur datemodified via formula numeric — fonctionne quelque
        // soit la locale du compte. Compare la datemodified de la SS au literal
        // TO_TIMESTAMP(sinceStr, 'YYYY-MM-DD HH24:MI:SS').
        // sinceStr doit être au format 'YYYY-MM-DD HH:MM:SS' (UTC).
        // Échappe les apostrophes dans la string (paranoïa).
        var safe = String(sinceStr).replace(/'/g, "''");
        return {
            name: 'formulanumeric',
            operator: 'greaterthanorequalto',
            formula: "CASE WHEN {datemodified} >= TO_TIMESTAMP('"
                + safe + "', 'YYYY-MM-DD HH24:MI:SS') THEN 1 ELSE 0 END",
            values: ['1']
        };
    }

    function listSavedSearches(offset, limit, since) {
        // Le pseudo-record `savedsearch` permet de lister les SS via une SS classique.
        // On combine 2 filtres :
        //   - inclusion explicite des actives ET inactives (NetSuite filtre les
        //     inactives par défaut sur ce record type)
        //   - si `since` est fourni : datemodified >= since (mode incremental)
        // NB: les colonnes `descr` (description) et `ispublic` ne sont pas exposées
        // sur le record type `savedsearch` dans ce compte. On reste sur le set
        // minimum de colonnes confirmées valides. `is_public` est récupéré via
        // search.load() dans l'endpoint `?action=get`.
        //
        // Filtre `isinactive` : NetSuite filtre AUTOMATIQUEMENT les inactives sur
        // ce record type (comme dans l'UI Lists > Saved Searches qui a un toggle
        // "Show Inactives" décoché par défaut). On force l'inclusion explicite
        // via un OR qui matche les deux états.
        var filters = [
            [['isinactive', 'is', 'F'], 'OR', ['isinactive', 'is', 'T']]
        ];
        if (since) {
            filters.push('AND');
            filters.push([_buildLastmodFilter(since)]);
        }

        var ssSearch = search.create({
            type: search.Type.SAVED_SEARCH,
            filters: filters,
            columns: [
                search.createColumn({ name: 'internalid' }),
                search.createColumn({ name: 'id' }),
                search.createColumn({ name: 'title' }),
                search.createColumn({ name: 'recordtype' }),
                search.createColumn({ name: 'owner' }),
                search.createColumn({ name: 'isinactive' }),
                search.createColumn({ name: 'datecreated' }),
                search.createColumn({ name: 'datemodified' })
            ]
        });

        var pageSize = 1000;
        var pageData = ssSearch.runPaged({ pageSize: pageSize });

        var startIdx = offset || 0;
        var endIdx = startIdx + (limit || pageSize);

        var idx = 0;
        var totalCount = 0;
        var results = [];

        pageData.pageRanges.forEach(function (pageRange) {
            var page = pageData.fetch({ index: pageRange.index });
            page.data.forEach(function (row) {
                if (idx >= startIdx && idx < endIdx) {
                    results.push({
                        internalid: row.id,
                        scriptid: row.getValue({ name: 'id' }),
                        title: row.getValue({ name: 'title' }),
                        recordtype: row.getValue({ name: 'recordtype' }),
                        owner_id: row.getValue({ name: 'owner' }),
                        owner: row.getText({ name: 'owner' }),
                        is_inactive: row.getValue({ name: 'isinactive' }) === 'T'
                            || row.getValue({ name: 'isinactive' }) === true,
                        date_created: row.getValue({ name: 'datecreated' }),
                        date_modified: row.getValue({ name: 'datemodified' })
                    });
                }
                idx++;
                totalCount++;
            });
        });

        return {
            total: totalCount,
            offset: startIdx,
            limit: (limit || pageSize),
            returned: results.length,
            items: results
        };
    }

    /* ------------------------------------------------------------------------ */
    /*  get                                                                     */
    /* ------------------------------------------------------------------------ */

    /**
     * Sérialise une `search.Filter` en JSON simple.
     */
    function serializeFilter(f) {
        if (!f) return null;
        return {
            name: f.name || null,
            join: f.join || null,
            operator: f.operator || null,
            summary: f.summary || null,
            formula: f.formula || null,
            // values est typé Array OU string selon les operators ; on normalise en array
            values: normalizeValues(f.values),
            isnot: !!f.isnot,
            isor: !!f.isor,
            leftparens: f.leftparens || 0,
            rightparens: f.rightparens || 0
        };
    }

    function normalizeValues(v) {
        if (v === null || typeof v === 'undefined') return null;
        if (Array.isArray(v)) return v;
        return [v];
    }

    /**
     * Sérialise une `search.Column` en JSON simple.
     */
    function serializeColumn(c) {
        if (!c) return null;
        var sortDir = null;
        try { sortDir = c.sort || null; } catch (e) { sortDir = null; }
        return {
            name: c.name || null,
            join: c.join || null,
            summary: c.summary || null,
            formula: c.formula || null,
            label: c.label || null,
            sort: sortDir,
            // function (renvoyé en `function_id`) : ex 'percentOfTotal', etc.
            function_id: (typeof c.function !== 'undefined') ? c.function : null
        };
    }

    function getSavedSearchDefinition(idOrScriptId) {
        // search.load accepte soit l'internalid (numerique) soit le scriptid (text).
        var loadArg;
        var asInt = parseInt(idOrScriptId, 10);
        if (!isNaN(asInt) && String(asInt) === String(idOrScriptId)) {
            loadArg = { id: asInt };
        } else {
            loadArg = { id: idOrScriptId };
        }

        var ss = search.load(loadArg);

        // filter_expression : forme normalisée Oracle ([[...], 'AND', [...]] etc.)
        var filterExpr = null;
        try {
            filterExpr = ss.filterExpression;
        } catch (e) {
            filterExpr = null;
        }

        // filters
        var filtersOut = [];
        var filterDefs = ss.filters || [];
        for (var i = 0; i < filterDefs.length; i++) {
            try {
                filtersOut.push(serializeFilter(filterDefs[i]));
            } catch (e) {
                filtersOut.push({ error: 'serialize_filter_failed: ' + e.message });
            }
        }

        // columns
        var colsOut = [];
        var colDefs = ss.columns || [];
        for (var j = 0; j < colDefs.length; j++) {
            try {
                colsOut.push(serializeColumn(colDefs[j]));
            } catch (e) {
                colsOut.push({ error: 'serialize_column_failed: ' + e.message });
            }
        }

        return {
            internalid: ss.id,
            scriptid: ss.searchId,
            title: ss.title,
            recordtype: ss.searchType,
            is_public: ss.isPublic === true,
            filter_expression: filterExpr,
            filters: filtersOut,
            columns: colsOut
        };
    }

    /* ------------------------------------------------------------------------ */
    /*  router                                                                  */
    /* ------------------------------------------------------------------------ */

    function _safeStringify(payload) {
        try {
            return JSON.stringify(payload);
        } catch (e) {
            // Si quelque chose dans payload n'est pas sérialisable, on dégrade gracefully
            return JSON.stringify({
                error: 'JSON.stringify failed: ' + (e && e.message ? e.message : String(e))
            });
        }
    }

    function get(context) {
        var action = (context && context.action) ? context.action : 'list';
        var payload;
        try {
            if (action === 'list') {
                var offset = parseInt((context && context.offset) || '0', 10);
                var limit = parseInt((context && context.limit) || '1000', 10);
                var since = (context && context.since) ? String(context.since) : null;
                payload = listSavedSearches(offset, limit, since);
            } else if (action === 'get') {
                if (!context || !context.id) {
                    payload = { error: 'Missing required parameter: id', action: 'get' };
                } else {
                    payload = getSavedSearchDefinition(context.id);
                }
            } else {
                payload = { error: 'Unknown action: ' + action, action: action };
            }
        } catch (e) {
            try { log.error({ title: 'saved_search_reader.' + action, details: e }); }
            catch (logErr) { /* swallow */ }
            payload = {
                error: (e.name || 'Error') + ': ' + (e.message || String(e)),
                action: action,
                stack: e.stack || null
            };
        }
        // IMPORTANT: stringify avant return — sinon UNEXPECTED_ERROR sur ce compte.
        return _safeStringify(payload);
    }

    return { get: get };
});
