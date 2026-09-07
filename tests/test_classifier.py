import unittest

from j0627_uwl.classifier import fit_external_classifier, posterior_high


class ClassifierTests(unittest.TestCase):
    def test_separated_mixture_is_accepted(self):
        values = [-2.2, -2.1, -2.0, -1.9, -1.8] * 5 + [4.8, 4.9, 5.0, 5.1, 5.2] * 5
        settings = {"minimum_delta_bic": 10.0, "minimum_component_separation": 1.5}
        model = fit_external_classifier(values, settings)
        self.assertTrue(model["accepted"])
        self.assertLess(posterior_high(-2.0, model), 0.01)
        self.assertGreater(posterior_high(5.0, model), 0.99)


if __name__ == "__main__":
    unittest.main()
