from novel_ai.domain.prose_length import ProseLengthPolicy


def test_length_policy_treats_target_as_guidance() -> None:
    policy = ProseLengthPolicy(target=2500)

    assert policy.preferred_minimum == 2125
    assert policy.preferred_maximum == 3000
    assert policy.expansion_trigger == 1875
    assert not policy.should_expand(2000)
    assert policy.should_expand(1800)


def test_length_policy_only_rejects_extreme_outputs() -> None:
    policy = ProseLengthPolicy(target=2500)

    assert policy.is_sane(1600)
    assert policy.is_sane(4000)
    assert not policy.is_sane(1000)
    assert not policy.is_sane(4500)
