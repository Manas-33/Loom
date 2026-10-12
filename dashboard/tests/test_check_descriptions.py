"""Description check (scripts/check_descriptions.py): reading the model's years answer. No model, no database."""
import importlib
import unittest

importlib.import_module('dashboard.app')  # puts scripts/ on the path
import check_descriptions as cd


def answer(**extra):
    return {**dict(early_career='Yes', years_required='', grad_year='', us_location='Yes',
                   needs_clearance_or_citizenship=False, sponsorship='not stated', phd_required=False,
                   min_gpa='', internship=False, bucket='generalist', reason='Early-career role.'), **extra}


class MinYearsTests(unittest.TestCase):
    def check(self, cases):
        for text, want in cases:
            with self.subTest(text=text):
                self.assertEqual(cd.min_years(text), want)

    def test_floors_and_ranges(self):
        self.check([('', 0), (None, 0), ('0', 0), ('1+', 1), ('2+', 2), ('2+ years', 2), ('0-2', 0),
                    ('3-5', 3), ('3 to 5 years', 3), ('at least 2 years', 2), ('minimum 3 years', 3),
                    ('2 years 6 months', 2), ('Up to two years', 0)])

    def test_ceilings_are_no_minimum(self):
        self.check([('Up to 2 years', 0), ('up to 3', 0), ('2 years or less', 0), ('2 or fewer years', 0),
                    ('3 yrs or under', 0), ('<= 2', 0), ('<2', 0), ('≤ 2 years', 0), ('max 2', 0),
                    ('Max. 3 years', 0), ('a maximum of 2 years', 0), ('2 years max', 0), ('at most 2', 0),
                    ('no more than 2 years', 0), ('less than 2 years', 0), ('under 3 years', 0)])

    def test_months_round_down_to_years(self):
        self.check([('2 months', 0), ('6+ months', 0), ('6-12 months', 0), ('11 mos', 0), ('12 months', 1),
                    ('18 months', 1), ('24 months', 2), ('36+ months', 3), ('up to 24 months', 0)])


class DecideTests(unittest.TestCase):
    def test_up_to_two_years_passes(self):  # handshake:11603060, Hologic Associate Applied AI Engineer
        self.assertEqual(cd.decide(answer(years_required='Up to 2 years'), 3.5)[0], 'pass')

    def test_months_of_internship_pass_the_years_cut(self):  # handshake:11570999, CoStar
        self.assertEqual(cd.decide(answer(years_required='2 months'), 3.5)[0], 'pass')
        self.assertEqual(cd.decide(answer(years_required='2 months', sponsorship='not offered'), 3.5, True)[:2],
                         ('drop', 'no visa sponsorship'))

    def test_two_years_minimum_still_drops(self):
        self.assertEqual(cd.decide(answer(years_required='2+'), 3.5)[:2], ('drop', 'needs 2+ years'))
