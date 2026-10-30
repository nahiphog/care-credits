"""Budget filtering must retain explicitly free courses without inventing FX conversions."""
import unittest
from backend.tests import test_portal as fixture
from models import Course
from repository.model_helpers import fill_course


class CatalogueBudgetTests(unittest.TestCase):
    setUp = fixture.PortalTests.setUp
    tearDown = fixture.PortalTests.tearDown
    login = fixture.PortalTests.login

    def test_free_unknown_currency_is_included_positive_unknown_is_not(self):
        with self.Session() as db:
            for label, fee, currency in [('Free', 0, None), ('Unknown', 5, None), ('MYR', 10, 'MYR')]:
                course = fill_course(Course(source_key='budget-' + label), fixture.sample('Budget ' + label))
                course.fee, course.currency = fee, currency
                db.add(course)
            db.commit()
        for budget, expected in [(0, {'Budget Free'}), (10, {'Budget Free', 'Budget MYR'})]:
            with self.subTest(budget=budget):
                response = self.client.get(f'/api/v1/trainings?q=Budget&period=all&max_fee_myr={budget}')
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual({row['title'] for row in response.json()['items']}, expected)
