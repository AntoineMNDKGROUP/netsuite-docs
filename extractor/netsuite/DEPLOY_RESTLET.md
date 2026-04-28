# Déploiement de la RESTlet `file_reader`

Procédure pas-à-pas pour exposer le contenu des fichiers du File Cabinet via une RESTlet.

## 1. Upload du script dans le File Cabinet

1. Dans NetSuite : **Documents → Files → File Cabinet**
2. Navigue dans le dossier **`SuiteScripts`** (ou crée un sous-dossier `SuiteScripts/Documentation Hub` pour ranger).
3. Clique **Add File**.
4. Upload le fichier : `extractor/netsuite/file_reader_restlet.js`.
5. **File Type** : `JavaScript` (devrait être détecté automatiquement).
6. Save.
7. **Note l'ID interne du fichier** (visible dans l'URL ou dans la liste des fichiers).

## 2. Création du Script record

1. **Customization → Scripting → Scripts → New**
2. **Script File** : sélectionne le `file_reader_restlet.js` qu'on vient d'uploader.
3. Clique **Create Script Record**.
4. Type : **RESTlet** (devrait être pré-rempli depuis le `@NScriptType`).
5. **Name** : `Documentation Hub - File Reader`
6. **ID** : `_doc_hub_file_reader` (NetSuite ajoutera le préfixe `customscript_` automatiquement).
7. **Description** : `Lecture des fichiers du File Cabinet pour la doc app`.
8. Save.

## 3. Création du Script Deployment

1. Dans la page du script, onglet **Deployments** → **New**
2. **Title** : `Documentation Hub - File Reader Deployment`
3. **ID** : `_doc_hub_file_reader_dep`
4. **Status** : **Released**
5. **Audience** :
   - Tu peux laisser default OU restreindre au rôle `Documentation Reader`
6. Save.
7. Une fois sauvegardé, **note l'External URL** affichée dans la page du déploiement, du format :
   ```
   https://4817474-sb1.suitetalk.api.netsuite.com/app/site/hosting/restlet.nl?script=XXXX&deploy=YYYY
   ```
   - **`script=XXXX`** = l'internal ID du Script (numérique)
   - **`deploy=YYYY`** = l'internal ID du Deployment (numérique)

## 4. Test rapide en navigateur ou curl

Pas testable dans un browser direct (besoin OAuth), mais on va le tester via Python.

## 5. Ajouter au `.env`

Édite `extractor/.env` et ajoute :
```
NS_FILE_READER_SCRIPT_ID=XXXX
NS_FILE_READER_DEPLOY_ID=YYYY
```

(Remplace XXXX et YYYY par les valeurs notées à l'étape 3.)

## 6. Test

```bash
./bin/run.sh extract --no-scripts --no-fields --no-custom-records --no-system-notes --limit 5
```

Si tout est bon : `'downloaded': 5, 'failed': 0`. Sinon, le log indiquera l'erreur précise.

## Permission requise sur le rôle

Le rôle `Documentation Reader` doit avoir au minimum :
- **Documents and Files** : View (déjà demandé)
- **SuiteScript** : View (déjà présent)
- Le déploiement doit être accessible au rôle (étape 3, audience).
