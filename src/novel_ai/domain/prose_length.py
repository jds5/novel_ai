from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProseLengthPolicy:
    """Quality-first chapter length guidance with only broad sanity limits."""

    target: int
    preferred_min_ratio: float = 0.85
    preferred_max_ratio: float = 1.20
    expansion_trigger_ratio: float = 0.75
    hard_min_ratio: float = 0.50
    hard_max_ratio: float = 1.70

    @property
    def preferred_minimum(self) -> int:
        return round(self.target * self.preferred_min_ratio)

    @property
    def preferred_maximum(self) -> int:
        return round(self.target * self.preferred_max_ratio)

    @property
    def expansion_trigger(self) -> int:
        return round(self.target * self.expansion_trigger_ratio)

    @property
    def hard_minimum(self) -> int:
        return round(self.target * self.hard_min_ratio)

    @property
    def hard_maximum(self) -> int:
        return round(self.target * self.hard_max_ratio)

    def should_expand(self, actual: int) -> bool:
        return actual < self.expansion_trigger

    def is_sane(self, actual: int) -> bool:
        return self.hard_minimum <= actual <= self.hard_maximum

    def prompt_contract(self) -> dict[str, object]:
        return {
            "target": self.target,
            "preferredRange": {
                "minimum": self.preferred_minimum,
                "maximum": self.preferred_maximum,
            },
            "expansionTriggerBelow": self.expansion_trigger,
            "hardSanityRange": {
                "minimum": self.hard_minimum,
                "maximum": self.hard_maximum,
            },
            "countingRule": "统计 prose 中的非空白字符",
            "priority": "行文流畅、叙事完整和语言质量优先于机械凑齐目标字数",
        }
