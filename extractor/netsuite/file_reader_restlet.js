/**
 * RESTlet pour exposer le contenu des fichiers du File Cabinet (v4 - JSON.stringify return).
 *
 * GET https://{account}.restlets.api.netsuite.com/app/site/hosting/restlet.nl
 *     ?script={SCRIPT_ID}&deploy={DEPLOY_ID}&id={fileId}
 *
 * IMPORTANT : on retourne JSON.stringify(...) — sur ce compte le framework refuse
 * un objet brut et fail en UNEXPECTED_ERROR sinon.
 *
 * @NApiVersion 2.1
 * @NScriptType Restlet
 */
define(['N/file'], function (file) {

    function safeProp(obj, prop) {
        try {
            var v = obj[prop];
            return (v === undefined) ? null : v;
        } catch (e) { return null; }
    }

    function errStr(e) {
        try { return e && e.message ? String(e.message) : String(e); }
        catch (x) { return 'unknown'; }
    }

    function errCode(e) {
        try { return String(e && e.name ? e.name : ''); } catch (x) { return ''; }
    }

    function safeLog(level, title, details) {
        try {
            // log est disponible globalement dans les RESTlets SuiteScript 2.x
            if (level === 'error') log.error(title, details);
            else log.audit(title, details);
        } catch (e) { /* swallow */ }
    }

    function get(params) {
        try {
            safeLog('audit', 'FileReader request', JSON.stringify(params || {}));

            var rawId = (params && params.id) ? params.id : null;
            if (!rawId) {
                return JSON.stringify({ error: 'Missing required parameter: id' });
            }

            var fileId = parseInt(rawId, 10);
            if (isNaN(fileId)) {
                return JSON.stringify({ error: 'Invalid id: ' + rawId });
            }

            var result = { id: fileId };

            // Load
            var f;
            try {
                f = file.load({ id: fileId });
            } catch (e) {
                safeLog('error', 'file.load failed', 'id=' + fileId + ' err=' + errStr(e));
                return JSON.stringify({
                    error: 'file.load failed: ' + errStr(e),
                    code: errCode(e),
                    fileId: fileId
                });
            }

            // Métadonnées
            result.name        = safeProp(f, 'name');
            result.fileType    = safeProp(f, 'fileType');
            result.size        = safeProp(f, 'size');
            result.encoding    = safeProp(f, 'encoding');
            result.description = safeProp(f, 'description');
            result.url         = safeProp(f, 'url');
            result.isOnline    = safeProp(f, 'isOnline');
            result.isInactive  = safeProp(f, 'isInactive');

            // folder peut être un objet
            var folder = safeProp(f, 'folder');
            if (folder && typeof folder === 'object') {
                result.folder = safeProp(folder, 'id') || safeProp(folder, 'name') || null;
            } else {
                result.folder = folder;
            }

            // Contenu (peut throw sur binaires)
            try {
                result.content = f.getContents();
                result.isText = true;
            } catch (e) {
                result.content = null;
                result.isText = false;
                result.contentError = errStr(e);
            }

            return JSON.stringify(result);

        } catch (fatal) {
            safeLog('error', 'FileReader fatal', errStr(fatal));
            return JSON.stringify({
                error: 'FATAL: ' + errStr(fatal),
                code: errCode(fatal)
            });
        }
    }

    return { get: get };
});
