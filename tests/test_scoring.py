from pmm.scoring import order_score, q_min, book_q, our_q, expected_daily_reward
from pmm.api import Book, Level


def test_order_score_shape():
    assert order_score(0.04, 0.0) == 1.0
    assert order_score(0.04, 0.02) == 0.25
    assert order_score(0.04, 0.04) == 0.0
    assert order_score(0.04, 0.05) == 0.0          # outside the band earns nothing
    assert order_score(0.04, 0.01, b=2) == 2 * (0.75 ** 2)


def test_q_min_rules():
    assert q_min(10, 4, 0.5) == 4                  # two-sided: the min
    assert q_min(12, 0, 0.5) == 4                  # single-sided: divided by 3
    assert q_min(12, 0, 0.95) == 0                 # extreme mids: two-sided only
    assert q_min(12, 9, 0.05) == 9


def test_book_q_counts_only_inside_band_and_min_size():
    b = Book("t", [Level(0.49, 100), Level(0.45, 100), Level(0.48, 5)], [Level(0.51, 100), Level(0.60, 1000)], 0.01, 5)
    q1, q2 = book_q(b, 0.04, 10)
    assert abs(q1 - order_score(0.04, 0.01) * 100) < 1e-9     # 0.45 is 5c away, 0.48 is below min size
    assert abs(q2 - order_score(0.04, 0.01) * 100) < 1e-9


def test_our_q_and_share():
    ours = our_q(0.04, 0.5, 0.48, 50, 0.52, 50)
    assert abs(ours - 0.25 * 50) < 1e-9
    assert abs(expected_daily_reward(100, ours, ours) - 50) < 1e-9
    assert expected_daily_reward(100, 0, 10) == 0
    assert expected_daily_reward(100, 10, 0) == 50                 # empty band: capped at max_share
    assert expected_daily_reward(100, 10, 0, max_share=0.2) == 20
