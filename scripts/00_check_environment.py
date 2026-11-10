"""Garde-fou environnement Odoo - Synchronisation Jira (Eurekam).

Ce script DOIT etre execute avant toute autre operation visant la base Odoo
(installation/maj du module, import, modification de donnees, lancement des tests).

Verifications effectuees :
    1. Le fichier config/odoo_test.json existe et est lisible.
    2. Le champ "environment" vaut bien "TEST".
    3. L'URL contient au moins un mot-cle de test
       (test, staging, dev, preprod, recette, sandbox).
    4. L'URL ne contient AUCUN mot-cle interdit (prod, production, main, ...).
    5. La base Odoo cible est resolue : soit via le champ "database" exact,
       soit via auto-decouverte sur "database_pattern" (regex). Sur odoo.sh,
       les bases de staging changent de nom a chaque rebuild d'ou l'utilite
       du pattern.
    6. La connexion XML-RPC a Odoo aboutit et la version serveur est lisible.
    7. L'authentification reussit avec les credentials fournis.
    8. L'UUID de la base (database.uuid) n'est PAS celui de la production
       (la sandbox est rechargee souvent : on verifie a chaque fois).

En cas d'echec d'une de ces verifications, le script s'arrete avec un code != 0
et toute operation appelante doit etre annulee.

Usage :
    python scripts/00_check_environment.py
    python scripts/00_check_environment.py --config config/odoo_test.json
    python scripts/00_check_environment.py --quiet
    python scripts/00_check_environment.py --skip-connection
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xmlrpc.client
from pathlib import Path

# ---------------------------------------------------------------------------
# Codes de sortie
# ---------------------------------------------------------------------------
EXIT_OK = 0
EXIT_CONFIG_MISSING = 10
EXIT_CONFIG_INVALID = 11
EXIT_ENV_NOT_TEST = 20
EXIT_URL_NOT_TEST = 21
EXIT_URL_FORBIDDEN = 22
EXIT_CONNECTION_FAILED = 30
EXIT_DB_RESOLUTION_FAILED = 31
EXIT_DB_PATTERN_FAIL = 32
EXIT_AUTH_FAILED = 33
EXIT_PRODUCTION_UUID = 40

PRODUCTION_UUID = "96e026e0-4de0-11e8-ae51-020000fbd37d"

DEFAULT_TEST_KEYWORDS = ("test", "staging", "dev", "preprod", "recette", "sandbox")
DEFAULT_FORBIDDEN_KEYWORDS = ("prod", "production", "main")


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------
def log(message: str, *, quiet: bool = False) -> None:
    if not quiet:
        print(message)


def fail(message: str, code: int) -> None:
    """Affiche le message d'erreur et termine avec le code donne."""
    print(message, file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------------------
# Chargement et validation de la configuration
# ---------------------------------------------------------------------------
def load_config(config_path: Path) -> dict:
    if not config_path.exists():
        fail(
            f"X STOP : fichier de configuration introuvable : {config_path}\n"
            f"  -> Copier config/odoo_test.json.example vers {config_path.name} "
            f"et y renseigner les credentials de la base de TEST.",
            EXIT_CONFIG_MISSING,
        )
    try:
        with config_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        fail(
            f"X STOP : fichier de configuration JSON invalide ({config_path}) : {exc}",
            EXIT_CONFIG_INVALID,
        )
    except OSError as exc:
        fail(f"X STOP : impossible de lire {config_path} : {exc}", EXIT_CONFIG_INVALID)


def check_environment_field(config: dict) -> None:
    env = config.get("environment")
    if env != "TEST":
        fail(
            f"X STOP : le champ 'environment' doit etre 'TEST' "
            f"(valeur actuelle : {env!r}).\n"
            f"  -> Refuser tout demarrage sur une configuration qui ne declare "
            f"pas explicitement TEST.",
            EXIT_ENV_NOT_TEST,
        )


def check_url(config: dict) -> str:
    url = config.get("url", "").strip()
    if not url:
        fail("X STOP : champ 'url' manquant ou vide dans la configuration.", EXIT_CONFIG_INVALID)

    url_lower = url.lower()
    safety = config.get("safety_check", {}) or {}

    # 1. Mots-cles de test obligatoires
    if safety.get("require_test_in_url", True):
        if not any(kw in url_lower for kw in DEFAULT_TEST_KEYWORDS):
            fail(
                f"X STOP : l'URL {url!r} ne contient aucun mot-cle de test "
                f"({', '.join(DEFAULT_TEST_KEYWORDS)}).\n"
                f"  -> Refuser de continuer : risque de viser la production.",
                EXIT_URL_NOT_TEST,
            )

    # 2. Mots-cles interdits
    forbidden = safety.get("forbidden_url_keywords", DEFAULT_FORBIDDEN_KEYWORDS)
    for mot in forbidden:
        mot_lower = mot.lower()
        if mot_lower in url_lower:
            # Cas particulier : 'prod' present dans 'preprod' -> autorise
            if mot_lower == "prod" and "preprod" in url_lower:
                continue
            fail(
                f"X STOP : l'URL {url!r} contient le mot-cle interdit {mot!r}.\n"
                f"  -> Risque de cibler la production. Operation annulee.",
                EXIT_URL_FORBIDDEN,
            )

    return url


# ---------------------------------------------------------------------------
# Resolution de la base : nom exact ou pattern regex (auto-decouverte)
# ---------------------------------------------------------------------------
def list_remote_databases(url: str, *, quiet: bool = False) -> list[str] | None:
    """Tente de lister les bases via XML-RPC. Renvoie None si le service est
    indisponible (certaines instances le desactivent pour la securite)."""
    try:
        db_proxy = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/db", allow_none=True)
        names = db_proxy.list()
        return list(names) if names else []
    except (xmlrpc.client.Fault, xmlrpc.client.ProtocolError, ConnectionError, OSError) as exc:
        log(f"   (info) service db.list() indisponible : {exc}", quiet=quiet)
        return None


def resolve_database(config: dict, url: str, *, quiet: bool = False) -> str:
    """Resout la base a utiliser :
    - Si 'database' est present, on l'utilise (et on warn s'il n'apparait plus
      dans la liste distante, ce qui suggere un rebuild odoo.sh).
    - Si 'database' est absent et 'database_pattern' present, on essaie
      d'auto-decouvrir via db.list() + regex.
    """
    expected_db = (config.get("database") or "").strip()
    pattern = (config.get("database_pattern") or "").strip()

    if not expected_db and not pattern:
        fail(
            "X STOP : ni 'database' ni 'database_pattern' n'est defini dans la configuration.\n"
            "  -> Renseigner au moins un des deux.",
            EXIT_CONFIG_INVALID,
        )

    available = list_remote_databases(url, quiet=quiet)

    # --- Cas 1 : nom exact fourni ---------------------------------------
    if expected_db:
        if available is not None and expected_db not in available:
            log(
                f"!! Avertissement : la base {expected_db!r} n'apparait pas dans "
                f"la liste distante {available}.\n"
                f"   La base a peut-etre ete renommee (rebuild odoo.sh ?).",
                quiet=quiet,
            )
            # Si pattern fourni, on essaie de retrouver la nouvelle base
            if pattern and available:
                try:
                    regex = re.compile(pattern)
                except re.error as exc:
                    fail(
                        f"X STOP : 'database_pattern' n'est pas une regex valide : {exc}",
                        EXIT_CONFIG_INVALID,
                    )
                candidates = [db for db in available if regex.match(db)]
                if len(candidates) == 1:
                    new_db = candidates[0]
                    log(
                        f"   -> Auto-discovery : nouvelle base detectee = {new_db!r}.\n"
                        f"      -> Mettre a jour 'database' dans config/odoo_test.json "
                        f"pour figer ce nom (sinon ce warning reapparaitra).",
                        quiet=quiet,
                    )
                    return new_db
        return expected_db

    # --- Cas 2 : pattern fourni sans nom exact --------------------------
    if available is None:
        fail(
            "X STOP : impossible de lister les bases (service db indisponible) "
            "et 'database' non fourni dans la config.\n"
            "  -> Renseigner 'database' explicitement.",
            EXIT_DB_RESOLUTION_FAILED,
        )
    if not available:
        fail("X STOP : aucune base disponible sur le serveur.", EXIT_DB_RESOLUTION_FAILED)

    try:
        regex = re.compile(pattern)
    except re.error as exc:
        fail(
            f"X STOP : 'database_pattern' n'est pas une regex valide : {exc}",
            EXIT_CONFIG_INVALID,
        )

    candidates = [db for db in available if regex.match(db)]
    if not candidates:
        fail(
            f"X STOP : aucune base ne matche {pattern!r}.\n  Disponibles : {available}",
            EXIT_DB_PATTERN_FAIL,
        )
    if len(candidates) > 1:
        fail(
            f"X STOP : plusieurs bases matchent {pattern!r} : {candidates}.\n"
            f"  -> Preciser 'database' explicitement pour lever l'ambiguite.",
            EXIT_DB_PATTERN_FAIL,
        )

    log(f"OK Base auto-decouverte via pattern : {candidates[0]!r}", quiet=quiet)
    return candidates[0]


# ---------------------------------------------------------------------------
# Connexion + authentification
# ---------------------------------------------------------------------------
def check_odoo_connection(
    config: dict, url: str, db_name: str, *, quiet: bool = False
) -> dict:
    try:
        common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common", allow_none=True)
        version_info = common.version()
    except (xmlrpc.client.Fault, xmlrpc.client.ProtocolError, ConnectionError, OSError) as exc:
        fail(
            f"X STOP : connexion XML-RPC echouee sur {url} : {exc}\n"
            f"  -> Verifier l'URL, la connectivite reseau et que le serveur Odoo repond.",
            EXIT_CONNECTION_FAILED,
        )

    server_version = version_info.get("server_version", "?")
    log(f"OK Connexion XML-RPC reussie. Version serveur : {server_version}", quiet=quiet)

    # Authentification : on accepte 'password' (mot de passe utilisateur OU cle API)
    # ou l'ancien champ 'api_key' pour retrocompatibilite. Odoo XML-RPC traite
    # les deux de la meme maniere via common.authenticate().
    username = config.get("username", "").strip()
    secret = (config.get("password") or config.get("api_key") or "").strip()
    if not username:
        fail("X STOP : 'username' manquant dans la configuration.", EXIT_CONFIG_INVALID)
    if not secret:
        fail(
            "X STOP : 'password' (ou 'api_key') manquant dans la configuration.",
            EXIT_CONFIG_INVALID,
        )

    placeholders = {
        "REMPLACER_PAR_LE_MOT_DE_PASSE_OU_LA_CLE_API",
        "REMPLACER_PAR_LA_CLE_API_DE_TEST",
    }
    if secret in placeholders:
        fail(
            "X STOP : la valeur d'authentification est encore la valeur exemple. "
            "Renseigner le vrai mot de passe (ou cle API) de TEST dans config/odoo_test.json.",
            EXIT_CONFIG_INVALID,
        )

    try:
        uid = common.authenticate(db_name, username, secret, {})
    except (xmlrpc.client.Fault, xmlrpc.client.ProtocolError, ConnectionError, OSError) as exc:
        fail(
            f"X STOP : authentification echouee sur la base {db_name!r} : {exc}",
            EXIT_AUTH_FAILED,
        )

    if not uid:
        fail(
            f"X STOP : authentification refusee pour {username!r} sur la base {db_name!r}.\n"
            f"  -> Verifier l'utilisateur, le mot de passe et le nom exact de la base.",
            EXIT_AUTH_FAILED,
        )

    log(f"OK Authentification reussie (uid={uid}) sur la base {db_name!r}.", quiet=quiet)
    return {"version": version_info, "uid": uid, "database": db_name}


def check_not_production_uuid(config: dict, url: str, db_name: str, uid: int,
                              *, quiet: bool = False) -> str:
    """Refuse to continue when the database UUID is the production one."""
    secret = (config.get("password") or config.get("api_key") or "").strip()
    prod_uuid = (config.get("production_uuid") or PRODUCTION_UUID).strip().lower()
    try:
        models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object", allow_none=True)
        db_uuid = models.execute_kw(
            db_name, uid, secret, "ir.config_parameter", "get_param", ["database.uuid"])
    except (xmlrpc.client.Fault, xmlrpc.client.ProtocolError, ConnectionError, OSError) as exc:
        fail(f"X STOP : lecture de database.uuid impossible : {exc}", EXIT_PRODUCTION_UUID)
    db_uuid = (db_uuid or "").strip().lower()
    if not db_uuid:
        fail("X STOP : database.uuid vide ou illisible (droits administrateur requis).",
             EXIT_PRODUCTION_UUID)
    if db_uuid == prod_uuid:
        fail(f"X STOP : la base {db_name!r} porte l'UUID de la PRODUCTION ({db_uuid}).\n"
             f"  -> Operation annulee.", EXIT_PRODUCTION_UUID)
    log(f"OK UUID de la base : {db_uuid} (different de la production).", quiet=quiet)
    return db_uuid


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Garde-fou environnement Odoo (Synchronisation Jira) - "
                    "verifie qu'on cible bien la base de TEST."
    )
    parser.add_argument(
        "--config",
        default="config/odoo_test.json",
        help="Chemin vers le fichier de configuration (defaut: config/odoo_test.json)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="N'affiche que les erreurs (utile dans les scripts batch).",
    )
    parser.add_argument(
        "--skip-connection",
        action="store_true",
        help="Saute les verifications reseau (utile pour tester la config seule).",
    )
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    config = load_config(config_path)

    check_environment_field(config)
    url = check_url(config)

    log("", quiet=args.quiet)
    log("=" * 60, quiet=args.quiet)
    log(">> ENVIRONNEMENT : TEST", quiet=args.quiet)
    log(f">> URL           : {url}", quiet=args.quiet)
    log("=" * 60, quiet=args.quiet)

    if args.skip_connection:
        log("(--skip-connection) verifications reseau ignorees.", quiet=args.quiet)
        log("OK Verifications de configuration OK.", quiet=args.quiet)
        return EXIT_OK

    db_name = resolve_database(config, url, quiet=args.quiet)
    log(f">> Base resolue  : {db_name}", quiet=args.quiet)

    info = check_odoo_connection(config, url, db_name, quiet=args.quiet)
    check_not_production_uuid(config, url, db_name, info["uid"], quiet=args.quiet)

    log("", quiet=args.quiet)
    log("OK Toutes les verifications sont passees. Vous pouvez continuer.", quiet=args.quiet)
    log(
        f"   (base={info['database']}, uid={info['uid']}, "
        f"server_version={info['version'].get('server_version')})",
        quiet=args.quiet,
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
