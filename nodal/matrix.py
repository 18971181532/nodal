"""Dense linear algebra: LU decomposition with partial pivoting.

The same code path serves real (DC / transient) and complex (AC) systems,
because Python's arithmetic operators are generic and ``abs`` is the
modulus for complex numbers.  No numpy, no external solver.
"""


class SingularMatrixError(ValueError):
    """Raised when the MNA system has no unique solution."""


def lu_solve(a, b):
    """Solve A x = b by Gaussian elimination with partial pivoting.

    ``a`` is a list of rows (mutated copy is made), ``b`` a right-hand side.
    Works for float and complex entries alike.
    """
    n = len(b)
    if n == 0:
        return []
    m = [list(row) for row in a]
    x = list(b)
    for col in range(n):
        # partial pivot: largest magnitude on / below the diagonal
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-300:
            raise SingularMatrixError(
                "matrix is singular at column %d (floating node or "
                "conflicting sources?)" % col)
        if piv != col:
            m[col], m[piv] = m[piv], m[col]
            x[col], x[piv] = x[piv], x[col]
        inv = 1.0 / m[col][col]
        for r in range(col + 1, n):
            factor = m[r][col] * inv
            if factor == 0:
                continue
            m[r][col] = 0.0
            for c in range(col + 1, n):
                m[r][c] -= factor * m[col][c]
            x[r] -= factor * x[col]
    # back substitution
    for r in range(n - 1, -1, -1):
        acc = x[r]
        for c in range(r + 1, n):
            acc -= m[r][c] * x[c]
        x[r] = acc / m[r][r]
    return x


def lu_factor(a):
    """Return (LU, perm) so repeated right-hand sides can reuse the factor.

    ``LU`` holds L (unit diagonal, below) and U (on / above) in one matrix.
    ``perm`` records the row swaps.
    """
    n = len(a)
    m = [list(row) for row in a]
    perm = list(range(n))
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-300:
            raise SingularMatrixError("matrix is singular at column %d" % col)
        if piv != col:
            m[col], m[piv] = m[piv], m[col]
            perm[col], perm[piv] = perm[piv], perm[col]
        inv = 1.0 / m[col][col]
        for r in range(col + 1, n):
            m[r][col] *= inv
            factor = m[r][col]
            for c in range(col + 1, n):
                m[r][c] -= factor * m[col][c]
    return m, perm


def lu_substitute(lu, perm, b):
    """Solve using a factorisation produced by :func:`lu_factor`."""
    n = len(b)
    x = [b[perm[i]] for i in range(n)]
    for r in range(n):
        acc = x[r]
        for c in range(r):
            acc -= lu[r][c] * x[c]
        x[r] = acc
    for r in range(n - 1, -1, -1):
        acc = x[r]
        for c in range(r + 1, n):
            acc -= lu[r][c] * x[c]
        x[r] = acc / lu[r][r]
    return x


def determinant(a):
    """Determinant via LU (sign tracked through row swaps)."""
    n = len(a)
    m = [list(row) for row in a]
    sign = 1.0
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-300:
            return 0.0
        if piv != col:
            m[col], m[piv] = m[piv], m[col]
            sign = -sign
        inv = 1.0 / m[col][col]
        for r in range(col + 1, n):
            factor = m[r][col] * inv
            for c in range(col + 1, n):
                m[r][c] -= factor * m[col][c]
    det = sign
    for i in range(n):
        det *= m[i][i]
    return det


def residual(a, x, b):
    """max |A x - b|, used to report solve quality."""
    worst = 0.0
    for i, row in enumerate(a):
        acc = 0.0
        for j, v in enumerate(row):
            acc += v * x[j]
        worst = max(worst, abs(acc - b[i]))
    return worst
