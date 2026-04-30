# ndk-netsuite (plugin Cowork)

Agent Claude pour l'equipe technique NDK : exploration, debug et impact
analysis du compte NetSuite **4817474-sb1**. L'agent s'appuie sur la base
Supabase `ndk-netsuite-docs` mise a jour chaque nuit par l'extracteur
`extractor/`. Il **apprend des corrections de l'equipe** via une couche
memoire (pgvector) et une knowledge base Markdown versionnee.

## Composants

### Skills

- **`ndk-netsuite-context`** : charge automatiquement quand l'utilisateur
  pose une question NetSuite. Contient le schema Supabase, les
  conventions NDK et les patterns SQL frequents.

### Commandes

| Commande | Use case |
|----------|----------|
| `/ns-impact-field <custbody_xxx>` | Qui utilise ce custom field ? Scripts, saved searches, custom records |
| `/ns-impact-script <scriptid>` | Quels deployments, qui appelle ce script, derniers updates |
| `/ns-explain-script <scriptid>` | Explication en francais clair de ce que fait un script |
| `/ns-find-by-usage <terme>` | Recherche large : qui mentionne ce terme dans NS ? |
| `/ns-recent-updates [24h\|7d\|30d]` | Brief des dernieres modifications detectees |
| `/ns-correct [memory_id] <texte>` | Corriger une reponse de l'agent (apprentissage) |
| `/ns-validate [helpful\|partial]` | Marquer la derniere reponse comme correcte |
| `/ns-memory-review [pending]` | Reviewer les promotions de knowledge en attente (Antoine) |

### Knowledge base

Versionnee dans Git, editable par l'equipe :

- `knowledge/conventions.md` : prefixes par equipe, naming, API version, ...
- `knowledge/modules/<prefix>.md` : un fichier par module NDK (NSA, LPS, ...)
- `knowledge/playbooks/*.md` : procedures (debug, deploy, ...)

### Couche memoire

Migration `0004_agent_memory.sql` cree :

- `agent_memory` (Q&A + embeddings + feedback)
- `agent_corrections` (corrections explicites avec embeddings)
- `agent_knowledge_promotions` (suggestions de cristallisation)
- Fonctions `search_agent_memory(...)` et `search_agent_corrections(...)`

## Setup

### Prerequis

1. Cowork desktop installe
2. Le connector Supabase officiel connecte avec le service_role_key du
   projet `ndk-netsuite-docs` (Settings > Connectors > Supabase)
3. Migration `0004_agent_memory.sql` appliquee sur la base

### Installation du plugin

1. Build du `.plugin` :
   ```bash
   cd "/Users/antoinemillet/Documents/Claude/Projects/Netsuite Documentation/plugin/ndk-netsuite"
   zip -r /tmp/ndk-netsuite.plugin . -x "*.DS_Store"
   ```
2. Glisser `/tmp/ndk-netsuite.plugin` dans Cowork (ou Settings > Plugins
   > Install from file)
3. Verifier que les commandes `/ns-*` apparaissent dans la liste

### Variables d'environnement

L'agent attend `${USER_EMAIL}` dans le contexte. Cowork le fournit
automatiquement via le profil utilisateur.

## Workflow d'apprentissage

```
[Dev pose une question]
        |
        v
[Agent cherche dans agent_memory --> match helpful ?]
   |                                      |
   non                                    oui
   |                                      v
   v                            [reutilise la reponse passee]
[Charge knowledge/]
[Requete Supabase]
[Genere reponse]
        |
        v
[Logge dans agent_memory (feedback = unverified)]
        |
        v
[Dev valide (/ns-validate) ou corrige (/ns-correct)]
        |
        +--> /ns-validate helpful : marque utile, reutilisable
        |
        +--> /ns-correct : insert dans agent_corrections
                |
                v
        [Cluster de corrections similaires detecte]
                |
                v
        [Cree une suggestion dans agent_knowledge_promotions]
                |
                v
        [Antoine review via /ns-memory-review]
                |
                +--> accept : Edit du fichier knowledge/*.md + commit
                +--> reject : noir sur le cluster
```

## Distribuer a l'equipe

Une fois testee localement, partager le `.plugin` a l'equipe :

```bash
cp /tmp/ndk-netsuite.plugin ~/Downloads/
# Slack le fichier dans #netsuite-tools
```

Chaque membre l'installe dans son Cowork. Tout le monde tape sur la meme
Supabase = meme memoire partagee. Les corrections d'un dev profitent a
toute l'equipe.

## Maintenance

- **Nightly** : l'extracteur `extractor/bin/run.sh extract` doit tourner
  chaque nuit pour rafraichir la base. GitHub Actions configure dans
  `.github/workflows/nightly-sync.yml`.
- **Cristallisation** : reviewer `agent_knowledge_promotions` une fois
  par semaine via `/ns-memory-review`.
- **Knowledge base** : tout change dans `knowledge/` doit passer en PR
  avec review.

## Limitations connues

- Workflows : on a la liste mais pas le contenu (NetSuite ne l'expose pas
  via SuiteQL).
- Custom fields : par defaut pas reupdated chaque nuit (trop de faux
  positifs). Lancer manuellement avec `--with-fields` quand besoin.
- Embeddings : pas generes en temps reel (latence). Un job batch
  separe doit alimenter `agent_memory.embedding`.
