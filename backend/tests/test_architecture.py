"""Protect the live API/schema contract during the repository reconciliation."""
import json
from pathlib import Path
import unittest

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
        self.assertIs(portal_models, schema)
