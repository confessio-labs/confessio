# Minimum number of labeled sentences required to train/evaluate a classifier head.
MIN_DATASET_SIZE = 300


def get_test_size(dataset_size: int) -> int:
    """Stepped held-out test size (100, 200, 400, 800, ...), the largest 100*2^k still under a
    third of the dataset. Shared by the V1 head training and the joint V2 encoder fine-tune so both
    report a consistent held-out size."""
    assert dataset_size >= MIN_DATASET_SIZE

    third_size = dataset_size // 3
    test_size = 100
    while 2 * test_size < third_size:
        test_size *= 2

    return test_size


def is_significantly_different(accuracy1, accuracy2, n1, n2):
    if n1 == 0 or n2 == 0:
        return False

    # scipy costs ~0.7 s to import and is only needed here (encoder promotion), never on the
    # server import path. torch first: macOS duplicate-OpenMP segfault guard.
    import torch  # noqa: F401
    from scipy import stats

    nb_success1 = round(n1 * accuracy1)
    values1 = [1] * nb_success1 + [0] * (n1 - nb_success1)

    nb_success2 = round(n2 * accuracy2)
    values2 = [1] * nb_success2 + [0] * (n2 - nb_success2)
    t_stat, p_value = stats.ttest_ind(values1, values2)
    print(f"p_value: {p_value}")

    return p_value < 0.05


if __name__ == '__main__':
    print(is_significantly_different(0.875, 0.915, 400, 800))
