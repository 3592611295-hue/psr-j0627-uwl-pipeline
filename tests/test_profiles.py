import unittest

from j0627_uwl.profiles import (
    ProfileError,
    apply_circular_shift,
    best_circular_alignment,
    parse_pdv_text,
)


class ProfileTests(unittest.TestCase):
    def test_parse_four_column_pdv(self):
        text = "\n".join(f"0 0 {index} {float(index)}" for index in range(4))
        cube = parse_pdv_text(text, expected_nbin=4)
        self.assertEqual(cube[(0, 0)], [0.0, 1.0, 2.0, 3.0])

    def test_duplicate_coordinate_is_rejected(self):
        text = "0 0 0 1\n0 0 0 2\n"
        with self.assertRaises(ProfileError):
            parse_pdv_text(text, expected_nbin=1)

    def test_alignment_shift_definition(self):
        reference = [0.0, 1.0, 0.0, -0.2]
        target = [0.0, -0.2, 0.0, 1.0]
        shift, corr = best_circular_alignment(reference, target)
        self.assertEqual(shift, 2)
        self.assertAlmostEqual(corr, 1.0)
        self.assertEqual(apply_circular_shift(target, shift), reference)


if __name__ == "__main__":
    unittest.main()
