# Setup pas-à-pas

## 1. Comptes externes

- [ ] Compte GitHub créé (username : ______)
- [ ] Compte Supabase créé (login GitHub)
- [ ] Projet Supabase `netsuite-docs` créé en région Europe
- [ ] Mot de passe DB Supabase noté en lieu sûr

## 2. NetSuite Sandbox – Préparer l'integration

À faire dans le compte NetSuite sandbox avec un rôle Administrator.

### 2.1 Activer les fonctionnalités nécessaires

`Setup → Company → Enable Features → SuiteCloud`
- [ ] `REST WEB SERVICES` (Token-Based Authentication section) → coché
- [ ] `TOKEN-BASED AUTHENTICATION` → coché
- [ ] `OAuth 2.0` (optionnel, on utilise OAuth 1.0 / TBA pour démarrer)

### 2.2 Créer un rôle dédié "Documentation Reader"

`Setup → Users/Roles → Manage Roles → New`
- Name : `Documentation Reader`
- Permissions minimales (Permissions tab → Setup) :
  - `Log in using Access Tokens` : Full
  - `REST Web Services` : Full
  - `SuiteScript` : View
  - `Custom Body Fields` : View
  - `Custom Column Fields` : View
  - `Custom Entity Fields` : View
  - `Custom Item Fields` : View
  - `Custom Transaction Fields` : View
  - `Custom Record Types` : View
  - `Workflow` : View
  - `Saved Search` : View
  - `User Access Tokens` : Full

### 2.3 Créer un user dédié

`Setup → Users/Roles → Manage Users → New`
- Email : `netsuite-docs-bot@ndk.group` (ou un alias)
- Role : `Documentation Reader`
- Cocher "Give Access"
- ⚠️ Ce user ne doit JAMAIS être utilisé pour autre chose.

### 2.4 Créer une integration record

`Setup → Integrations → Manage Integrations → New`
- Name : `NetSuite Documentation Hub`
- State : Enabled
- Token-Based Authentication : ✅ coché
- TBA: Authorization Flow : décoché (on utilise des tokens user-spécifiques)
- User Credentials : décoché
- Sauvegarder
- ⚠️ **Copier immédiatement** `Consumer Key` et `Consumer Secret` (ils ne s'afficheront qu'une fois)

### 2.5 Générer les Access Tokens pour le user dédié

Se reconnecter en tant que le user `netsuite-docs-bot`, puis :
`Settings → Manage Access Tokens → New My Access Token`
- Application Name : `NetSuite Documentation Hub`
- Token Name : `Sandbox Extractor`
- ⚠️ **Copier immédiatement** `Token ID` et `Token Secret`

### 2.6 Récupérer l'Account ID

`Setup → Company → Company Information → Account ID`
- Format sandbox : `1234567_SB1`

## 3. Configuration locale du projet

```bash
cd "/Users/antoinemillet/Documents/Claude/Projects/Netsuite Documentation"
cp extractor/.env.example extractor/.env
# Éditer extractor/.env avec les valeurs récupérées plus haut
```

## 4. Application du schéma Supabase

À faire une fois les credentials NetSuite ok et le projet Supabase créé.
