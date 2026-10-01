from pmm.api import Book, Level


def test_adjusted_mid_ignores_dust():
    b = Book("t", [Level(0.49, 3), Level(0.40, 100)], [Level(0.51, 2), Level(0.60, 100)], 0.01, 5)
    assert b.mid == 0.50                                   # raw mid is set by two dust orders
    mid, spread = b.adjusted(20)
    assert mid == 0.50 and abs(spread - 0.20) < 1e-9       # real mid happens to agree, real spread is 20c
    b2 = Book("t", [Level(0.49, 3), Level(0.30, 100)], [Level(0.51, 100)], 0.01, 5)
    m2, s2 = b2.adjusted(20)
    assert abs(m2 - 0.405) < 1e-9 and abs(s2 - 0.21) < 1e-9
    assert Book("t", [Level(0.49, 3)], [Level(0.51, 100)], 0.01, 5).adjusted(20) == (None, None)
