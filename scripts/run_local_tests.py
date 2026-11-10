"""Run the pure-Python tests of eurekam_jira_sync WITHOUT Odoo.

Covers the HTTP client (``models/jira_client.py``) and the Jira -> Odoo
conversion rules (``models/jira_mapping.py``). The ORM tests
(``test_sync.py``, ``test_rules.py``) need an Odoo server: they run on the
Odoo.sh build of the sandbox branch.

No test calls the real Jira.

Usage (from the repository root):
    python scripts/run_local_tests.py
"""
import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_DIR = os.path.join(ROOT, 'module', 'eurekam_jira_sync')


def _package(name, path):
    """Register a package WITHOUT executing its __init__.py (which imports
    Odoo), so that relative imports between submodules still work."""
    pkg = types.ModuleType(name)
    pkg.__path__ = [path]
    sys.modules[name] = pkg
    return pkg


def main():
    _package('ejs', MODULE_DIR)
    _package('ejs.models', os.path.join(MODULE_DIR, 'models'))
    _package('ejs.tests', os.path.join(MODULE_DIR, 'tests'))
    from ejs.tests.cases_pure import ClientCases, MappingCases  # noqa: E402

    class LocalClientTests(ClientCases, unittest.TestCase):
        pass

    class LocalMappingTests(MappingCases, unittest.TestCase):
        pass

    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(LocalClientTests),
        loader.loadTestsFromTestCase(LocalMappingTests),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
