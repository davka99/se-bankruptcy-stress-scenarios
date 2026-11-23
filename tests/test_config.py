"""Sanity checks on the central configuration."""

from src import config


def test_every_source_code_maps_to_a_sector():
    assert set(config.TVA_CODE_TO_SECTOR.values()) == set(config.SECTORS)


def test_division_ranges_do_not_overlap():
    covered = []
    for lo, hi, _ in config.DIVISION_RANGES:
        covered.extend(range(lo, hi + 1))
    assert len(covered) == len(set(covered))
    assert 84 not in covered  # public administration has no bankruptcy group


def test_selection_period_precedes_test_period():
    assert config.SELECTION_END < config.TEST_START


def test_spec_grid_size_is_eight():
    # 5 lags for variant A + B + C + A without trend
    assert len(config.LAG_GRID) + 3 == 8
