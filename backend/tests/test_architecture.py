"""Protect the live API/schema contract during the repository reconciliation."""
import json
import ast
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / 'backend'
sys.path.insert(0, str(BACKEND))

from database import Base
from main import app
import portal_models
from models import schema


class ReconciliationContractTests(unittest.TestCase):
    def test_existing_routes_and_database_columns_are_preserved(self):
        expected = json.loads((Path(__file__).parent / 'fixtures/deployed_contract.json').read_text())
        actual = {
            'routes': sorted((r.path, sorted(r.methods), r.status_code)
                             for r in app.routes if hasattr(r, 'status_code')),
            'tables': {t.name: [(c.name, str(c.type), c.nullable, c.primary_key)
                                for c in t.columns] for t in Base.metadata.sorted_tables},
        }
        self.assertEqual(json.loads(json.dumps(actual)), expected)
        self.assertIs(portal_models.Account, schema.Account)
        self.assertIs(portal_models.Course, schema.Course)
        self.assertFalse(hasattr(schema, 'fill_course'))
        self.assertFalse(hasattr(schema, 'purge_expired_source_text'))


class LayerBoundaryTests(unittest.TestCase):
    def tree(self, path):
        return ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))

    def imports(self, tree):
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                yield from (alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                yield node.module or ''

    def test_main_composes_routers_without_alias_or_monolith(self):
        tree = self.tree(BACKEND / 'main.py')
        imports = set(self.imports(tree))
        self.assertNotIn('services.portal', imports)
        self.assertFalse(any(isinstance(node, ast.Attribute) and node.attr == 'modules' for node in ast.walk(tree)))
        self.assertTrue(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'FastAPI' for node in ast.walk(tree)))
        self.assertTrue(any(name == 'routers' or name.startswith('routers.') for name in imports))

    def test_services_have_no_http_validation_or_direct_database_access(self):
        violations = []
        forbidden_modules = {'fastapi', 'starlette', 'pydantic', 'sqlalchemy', 'main', 'portal_models', 'catalogue', 'schedule'}
        forbidden_calls = {'query', 'execute', 'get', 'add', 'add_all', 'delete', 'commit', 'flush', 'rollback', 'begin_nested', 'expire_all', 'get_bind'}
        for path in (BACKEND / 'services').glob('*.py'):
            # Legacy archival module is forbidden from active imports separately.
            if path.name == 'portal.py':
                continue
            tree = self.tree(path)
            for name in self.imports(tree):
                if name.split('.')[0] in forbidden_modules:
                    violations.append(f'{path.name}: forbidden import {name}')
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    receiver = node.func.value
                    if isinstance(receiver, ast.Name) and receiver.id in {'db', 'session'} and node.func.attr in forbidden_calls:
                        violations.append(f'{path.name}:{node.lineno}: direct database {node.func.attr}')
        self.assertEqual(violations, [])

    def test_active_backend_does_not_import_old_service_monolith(self):
        violations = []
        for path in BACKEND.rglob('*.py'):
            if 'tests' in path.parts or path.name == 'portal.py':
                continue
            for node in ast.walk(self.tree(path)):
                if isinstance(node, ast.ImportFrom) and (node.module == 'services.portal' or (node.module == 'services' and any(alias.name == 'portal' for alias in node.names))):
                    violations.append(str(path.relative_to(BACKEND)))
                if isinstance(node, ast.Import) and any(alias.name == 'services.portal' for alias in node.names):
                    violations.append(str(path.relative_to(BACKEND)))
        self.assertEqual(violations, [])

    def test_models_are_passive_storage_mappings(self):
        violations = []
        forbidden = {'fastapi', 'starlette', 'pydantic', 'services', 'repository', 'requests', 'httpx'}
        for path in (BACKEND / 'models').glob('*.py'):
            tree = self.tree(path)
            for name in self.imports(tree):
                if name.split('.')[0] in forbidden:
                    violations.append(f'{path.name}: {name}')
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {'query', 'execute', 'commit', 'flush', 'create_all'}:
                    violations.append(f'{path.name}:{node.lineno}: persistence operation')
        self.assertEqual(violations, [])

    def test_scraper_cannot_import_backend_or_database(self):
        violations = []
        for path in (ROOT / 'scraper').rglob('*.py'):
            if 'tests' in path.parts:
                continue
            for name in self.imports(self.tree(path)):
                if name.split('.')[0] in {'backend', 'database', 'models', 'repository', 'portal_models', 'sqlalchemy'}:
                    violations.append(f'{path.relative_to(ROOT)}: {name}')
        self.assertEqual(violations, [])
