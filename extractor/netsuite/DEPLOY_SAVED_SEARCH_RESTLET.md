# Déploiement de la RESTlet `saved_search_reader`

Procédure pas-à-pas pour exposer la définition complète des saved searches via une RESTlet.

> Cette RESTlet est nécessaire parce que l'API REST native NetSuite **n'expose pas**
> les définitions de saved searches (filtres, colonnes, joins). On a donc besoin
> d'un RESTlet qui fait `N/search.load(id)` et qui sérialise le résultat en JSON.

## 1. Upload du script dans le File Cabinet

1. Dans NetSuite : **Documents → Files → File Cabinet**
2. Navigue dans le dossier `SuiteScripts/Documentation Hub` (déjà créé pour le file_reader).
3. Clique **Add File**.
4. Upload le fichier : `extractor/netsuite/saved_search_reader_restlet.js`.
5. **File Type** : `JavaScript` (devrait être détecté automatiquement).
6. Save.

## 2. Création du Script record

1. **Customization → Scripting → Scripts → New**
2. **Script File** : sélectionne `saved_search_reader_restlet.js` qu'on vient d'uploader.
3. Clique **Create Script Record**.
4. Type : **RESTlet** (devrait être pré-rempli depuis le `@NScriptType`).
5. **Name** : `Documentation Hub - Saved Search Reader`
6. **ID** : `_doc_hub_search_reader` (NetSuite ajoutera le préfixe `customscript_` automatiquement → `customscript_doc_hub_search_reader`).
7. **Description** : `Lecture des définitions de saved searches pour la doc app`.
8. Save.

## 3. Création du Script Deployment

1. Dans la page du script, onglet **Deployments** → **New**
2. **Title** : `Documentation Hub - Saved Search Reader Deployment`
3. **ID** : `_doc_hub_search_reader_dep`
4. **Status** : **Released**
5. **Audience** :
   - Restreint au rôle `Documentation Reader` (recommandé, comme pour file_reader).
   - Ou laisse "All Roles" si tu préfères.
6. Save.
7. Une fois sauvegardé, **note les internal IDs** affichés dans l'External URL :
   ```
   https://4817474-sb1.suitetalk.api.netsuite.com/app/site/hosting/restlet.nl?script=XXXX&deploy=YYYY
   ```
   - `script=XXXX` = internal ID du Script
   - `deploy=YYYY` = internal ID du Deployment

## 4. Permissions à vérifier sur le rôle `Documentation Reader`

Le rôle doit avoir au minimum (en plus de ce qui est déjà demandé pour file_reader) :

- **Saved Search** : View
- **Setup → SuiteScript** : View
- **REST Web Services** : Full
- **Log in using Access Tokens** : Full

Si certaines saved searches sont restreintes (audience par rôle dans la SS elle-même),
elles ne seront pas listées par le RESTlet — c'est normal et désiré (on n'extrait
que ce que le user `Documentation Reader` peut voir).

## 5. Ajouter au `.env`

Édite `extractor/.env` et ajoute :

```
NS_SEARCH_READER_SCRIPT_ID=XXXX
NS_SEARCH_READER_DEPLOY_ID=YYYY
```

(Remplace XXXX et YYYY par les valeurs notées à l'étape 3.)

## 6. Test

```bash
cd extractor
./bin/run.sh saved-searches --limit 5
```

Si tout est bon : tu verras 5 saved searches en mode test, avec leur définition
complète (filters + columns) loggée. Sinon, le log indiquera l'erreur précise.

Pour lancer en mode "tous les NDK customs" (sans limit) :

```bash
./bin/run.sh saved-searches
```

## Endpoints exposés par la RESTlet

### `?action=list&offset=0&limit=1000`

Liste paginée des SS accessibles. Retourne :

```json
{
  "total": 1234,
  "offset": 0,
  "limit": 1000,
  "returned": 1000,
  "items": [
    {
      "internalid": "1234",
      "scriptid": "customsearch_nsa_dsv_warehouse",
      "title": "NSA - DSV Warehouse Inventory",
      "recordtype": "transaction",
      "owner_id": "468772",
      "owner": "Antoine Millet",
      "is_inactive": false,
      "is_public": true,
      "description": "Stock inventory at DSV warehouse...",
      "date_created": "01/15/2024",
      "date_modified": "03/22/2024"
    }
  ]
}
```

### `?action=get&id=1234`  (ou `&id=customsearch_xxx`)

Définition complète d'une SS. Retourne :

```json
{
  "internalid": "1234",
  "scriptid": "customsearch_nsa_dsv_warehouse",
  "title": "NSA - DSV Warehouse Inventory",
  "recordtype": "transaction",
  "is_public": true,
  "filter_expression": [["type","anyof","SalesOrd"],"AND",["mainline","is","T"]],
  "filters": [
    {
      "name": "type",
      "join": null,
      "operator": "anyof",
      "summary": null,
      "formula": null,
      "values": ["SalesOrd"],
      "isnot": false,
      "isor": false,
      "leftparens": 0,
      "rightparens": 0
    }
  ],
  "columns": [
    {
      "name": "tranid",
      "join": null,
      "summary": null,
      "formula": null,
      "label": "Document Number",
      "sort": "ASC",
      "function_id": null
    }
  ]
}
```
