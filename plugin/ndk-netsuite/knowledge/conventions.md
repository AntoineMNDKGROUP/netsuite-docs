# Conventions NDK pour NetSuite

> Ce fichier est la source de verite pour les conventions internes NDK.
> Toute correction de l'agent qui revele une convention manquante doit
> finir ici (apres review de tech lead).

## Prefixes par equipe / module

Les scripts internes a NDK suivent une nomenclature stricte. **Ne jamais
deroger**, meme pour un script "temporaire".

| Prefix | Equipe responsable | Domaine | Tech lead |
|--------|--------------------|---------|-----------|
| `NSA` | NDK Sales Automation | tout ce qui touche au cycle de vente (devis, SO, invoice) | _a remplir_ |
| `NUS` | NDK Utilities Stock | gestion d'entrepot, picking, inventaire | _a remplir_ |
| `LPS` | Logistics Process Suite | facturation logistique, contrats client, billing complexe | _a remplir_ |
| `LUS` | Logistics Utilities Suite | dispatch transporteurs, calcul de couts logistiques | _a remplir_ |
| `MU` | Misc Utilities | scripts utilitaires transverses, email, planificateur | _a remplir_ |

> **TODO** : remplir les tech leads pour permettre a l'agent de pinguer la
> bonne personne sur Slack quand un script est touche.

## Naming des scripts

Format attendu pour un fichier source : `<PREFIX>_<snake_case_purpose>.js`

```
NSA_invoice_validator.js              OK
NSA_validate_customer_credit.js       OK
nsa_validator.js                      KO  (prefix doit etre uppercase)
NSA-invoice-validator.js              KO  (snake_case, pas kebab)
nsavalidator.js                       KO  (prefix obligatoire avec separateur)
```

Le `scriptid` cote NetSuite suit la regle :
`customscript_<prefix_lower>_<purpose>` -- exemple
`customscript_nsa_invoice_validator`.

## Naming des deployments

Format : `customdeploy_<prefix_lower>_<purpose>[_<env>]`

`<env>` est optionnel et utilise quand il y a plusieurs deployments du
meme script (ex `_test`, `_prod`, ou un suffixe par filiale).

## Naming des custom fields

| Type | Prefix obligatoire | Exemple |
|------|--------------------|---------|
| body field (transaction) | `custbody_<prefix>_` | `custbody_lps_invoice_state` |
| entity field (customer/vendor/employee) | `custentity_<prefix>_` | `custentity_nsa_credit_score` |
| item field | `custitem_<prefix>_` | `custitem_nus_warehouse_zone` |
| sublist column | `custcol_<prefix>_` | `custcol_lps_billing_rate` |
| custom record field | `custrecord_<prefix>_` | `custrecord_lus_dispatch_carrier` |

Le prefix `<prefix>` correspond au prefix d'equipe en lowercase. Un field
LPS doit commencer par `custbody_lps_`, jamais `custbody_invoice_state`.

## Naming des saved searches

Format : `customsearch_<prefix>_<purpose>` -- meme regle que les scripts.

Les saved searches "publiques" partagees a toute la boite (KPI finance,
tableaux de bord direction) commencent par `customsearch_share_`.

## Naming des workflows

Format : `customworkflow_<prefix>_<purpose>`

Important : un workflow doit toujours etre couple a un User Event Script
qui logge ses transitions dans la table `<prefix>_workflow_log` (custom
record). C'est une regle interne pour avoir un audit fiable, NetSuite
n'expose pas l'historique des workflows en SuiteQL.

## Versionnage du code

- **Sandbox = source de verite de developpement**. On code et on teste sur
  `4817474-sb1`, jamais directement en prod.
- **Bundles** : on push de la sandbox vers la prod via les NetSuite Bundles.
  Pas de SDF deploy direct sans accord du tech lead.
- **Source files** : le code reside dans `/SuiteScripts/<Module>/<file>.js`
  ou `<Module>` correspond au prefix (ex `/SuiteScripts/LPS/`).

## API version

- Tous les nouveaux scripts en SuiteScript 2.1 (`@NApiVersion 2.1`).
- Les scripts 2.0 existants restent en place tant qu'ils marchent. Ne
  pas les migrer sans ticket dedie.
- Pas de SuiteScript 1.x. Si l'agent en repere un, le signaler comme
  candidat a la deprecation.

## Logging

Niveau `AUDIT` par defaut sur les User Events en prod. `DEBUG` autorise
en sandbox uniquement. Un script en prod avec `loglevel = DEBUG` doit
remonter une alerte dans le dashboard `/updates`.

## Credentials et secrets

- Aucun secret en dur dans le code source. Les API keys vont dans des
  Records `Custom List > Credentials` (custom record dedie).
- Les RESTlets internes utilisent OAuth 1.0 TBA (jamais Login API).

## Release schedule

- Deployments majeurs : mardi en debut d'apres-midi uniquement (pas le
  vendredi, pas en fin de mois).
- Hotfix : autorise n'importe quand mais doit etre mentionne dans Slack
  `#netsuite-hotfix` avec la liste des objets touches.

## Quand quelque chose ne respecte pas les conventions

1. Ne pas le corriger en silence -- creer un ticket Linear avec le label
   `netsuite-cleanup`.
2. Si c'est un script proprietaire NDK qui ne respecte pas le prefix, le
   considerer prioritaire (impact sur l'agent et la documentation).
3. Si c'est un module SuiteApp tiers, ne rien toucher : on documente la
   deviation, on ne corrige pas.
