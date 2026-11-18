import unittest

from nodal.matrix import (SingularMatrixError, determinant, lu_factor,
                          lu_solve, lu_substitute, residual)


class TestLu(unittest.TestCase):
    def test_2x2(self):
        x = lu_solve([[2.0, 1.0], [1.0, 3.0]], [5.0, 10.0])
        self.assertAlmostEqual(x[0], 1.0)
        self.assertAlmostEqual(x[1], 3.0)

    def test_pivot_required(self):
        # zero on the diagonal forces a row swap
        x = lu_solve([[0.0, 2.0], [1.0, 1.0]], [4.0, 3.0])
        self.assertAlmostEqual(x[0], 1.0)
        self.assertAlmostEqual(x[1], 2.0)

    def test_singular(self):
        with self.assertRaises(SingularMatrixError):
            lu_solve([[1.0, 2.0], [2.0, 4.0]], [1.0, 2.0])

    def test_residual_random(self):
        import random
        rng = random.Random(42)
        n = 12
        a = [[rng.uniform(-1, 1) + (n if i == j else 0)
              for j in range(n)] for i in range(n)]
        b = [rng.uniform(-1, 1) for _ in range(n)]
        x = lu_solve(a, b)
        self.assertLess(residual(a, x, b), 1e-9)

    def test_complex(self):
        # (1+j) x = 2j  ->  x = 2j/(1+j) = 1+j
        x = lu_solve([[1 + 1j]], [2j])
        self.assertAlmostEqual(x[0].real, 1.0)
        self.assertAlmostEqual(x[0].imag, 1.0)

    def test_complex_2x2(self):
        a = [[2j, 1.0], [1.0, -1j]]
        b = [3j, 2.0]
        x = lu_solve(a, b)
        self.assertLess(residual(a, x, b), 1e-12)

    def test_factor_reuse(self):
        a = [[4.0, 1.0], [1.0, 3.0]]
        lu, perm = lu_factor(a)
        for b in ([1.0, 2.0], [5.0, 0.0], [-3.0, 7.0]):
            x1 = lu_substitute(lu, perm, b)
            x2 = lu_solve(a, b)
            for u, v in zip(x1, x2):
                self.assertAlmostEqual(u, v)

    def test_determinant(self):
        self.assertAlmostEqual(determinant([[2.0, 1.0], [1.0, 3.0]]), 5.0)
        self.assertAlmostEqual(determinant([[1.0, 2.0], [2.0, 4.0]]), 0.0)

    def test_empty(self):
        self.assertEqual(lu_solve([], []), [])


if __name__ == "__main__":
    unittest.main()
