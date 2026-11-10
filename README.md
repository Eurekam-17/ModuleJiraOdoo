# Module Jira Odoo

Modules Odoo 18 d'**Eurekam** qui recopient dans Odoo, en lecture seule, les tickets,
versions et sprints Jira du développement Drugcam (projets DA, DC, DP), pour les
tableaux de bord et pour relier les tickets d'assistance aux corrections logicielles.

Spécification complète : [CLAUDE.md](CLAUDE.md).

| Module | Rôle | Dépendances |
|---|---|---|
| [`eurekam_jira_sync`](module/eurekam_jira_sync/README.md) | Cœur : client Jira, modèles `jira.*`, synchronisation planifiée, vues, paramètres | `base`, `mail` |
| [`eurekam_jira_helpdesk`](module/eurekam_jira_helpdesk/README.md) | Pont Assistance : clé Jira sur `helpdesk.ticket`, bloc « Développement », migration de l'ancienne propriété | `eurekam_jira_sync`, `helpdesk` (Entreprise) |

## Règles absolues

- **Lecture seule côté Jira** : aucune écriture, jamais.
- **Sandbox d'abord** : tout se fait sur `eurekam-sandbox.odoo.com`. Rien n'est installé
  en production (`eurekam.odoo.com`) sans validation écrite de Loïc.
- Le jeton d'API Atlassian ne passe jamais par le dépôt, un e-mail ou un chat : il est
  saisi directement dans les paramètres Odoo de la sandbox.

## Structure du dépôt

```
.
├── CLAUDE.md                       Spécification
├── README.md                       Ce fichier
├── config/
│   └── odoo_test.json.example      Modèle de connexion à la sandbox (le vrai fichier est ignoré par git)
├── scripts/
│   ├── 00_check_environment.py     Garde-fou : URL de test, base, authentification, UUID ≠ production
│   └── run_local_tests.py          Tests sans Odoo (client HTTP, règles de conversion)
└── module/
    ├── eurekam_jira_sync/
    └── eurekam_jira_helpdesk/
```

## Tests

```bash
python scripts/run_local_tests.py
```

Les tests ORM (`test_sync.py`, `test_rules.py`, `test_helpdesk.py`) s'exécutent dans
Odoo 18 : sur le build Odoo.sh de la branche `sandbox`, ou en local avec
`odoo -d test_jira --test-enable --stop-after-init -i eurekam_jira_sync --test-tags eurekam_jira`.

## Déploiement sur la sandbox Odoo.sh

Même principe que GestionContratMaintenance : ce dépôt est intégré comme **sous-module
git** du dépôt Odoo.sh du prestataire, `ScalizerOrg/eurekam`, **branche `sandbox`
uniquement** (jamais `staging`, `preprod` ni `production`).

Première intégration (une seule fois) :

```bash
git clone --branch sandbox https://github.com/ScalizerOrg/eurekam.git
cd eurekam
git submodule add -b main git@github.com:Eurekam-17/ModuleJiraOdoo.git Eurekam-17/ModuleJiraOdoo
git commit -m "[ADD] Eurekam-17/ModuleJiraOdoo (synchronisation Jira -> Odoo)"
git push origin sandbox
```

Mises à jour suivantes (sans cloner le sous-module) :

```bash
git clone --depth 1 --branch sandbox https://github.com/ScalizerOrg/eurekam.git
cd eurekam
git update-index --cacheinfo 160000,<SHA_COMPLET>,Eurekam-17/ModuleJiraOdoo
git commit -m "[UPD] ModuleJiraOdoo -> <sha court> (...)"
git push origin sandbox
```

Points d'attention (retour d'expérience GestionContratMaintenance) :
- Odoo.sh doit pouvoir lire le dépôt privé : clé de déploiement à ajouter
  (Odoo.sh → Settings → Submodules).
- **Un push n'est pas un déploiement** : vérifier que le build est vert, puis que le
  module est bien à jour sur la sandbox (version installée, date de mise à jour). Un
  build en échec laisse l'ancien code en ligne.
- Espacer les pushs : plusieurs pushs rapprochés font abandonner des builds. Pour
  relancer un build, pousser un commit vide sur `sandbox`, ne pas cliquer « Rebuild »
  (qui recharge une copie de la production et désinstalle les modules de test).
- Après chaque rechargement de la sandbox, l'installation et les paramètres sont à
  refaire (le nom de la base change aussi : `eurekam-sandbox-<build>`).

Après le build : Applications → Mettre à jour la liste → installer « Synchronisation
Jira » puis « Lien Assistance / Jira », et dérouler la recette décrite dans
[`module/eurekam_jira_sync/README.md`](module/eurekam_jira_sync/README.md).

## Auteur et licence

Eurekam — LGPL-3.
