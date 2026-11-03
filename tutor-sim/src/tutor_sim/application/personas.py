"""The sixteen pupil cards, the four tutor roles, and the roster."""

from tutor_sim.domain.models.identity import SimulationNamespace
from tutor_sim.domain.models.learner import HistoryEventRecord, PersonaLearnerRecord
from tutor_sim.domain.models.persona import (
    AgeBand,
    ErrorRate,
    FewShotTurn,
    PersonaCard,
    PupilLevel,
    Traits,
)
from tutor_sim.domain.models.tutor_role import TutorRoleCard

_LEVELS: tuple[PupilLevel, ...] = ("A1", "A2", "B1", "B2")
_L1 = ("es", "ot")
_AGES: tuple[tuple[int, AgeBand], ...] = ((13, "12-14"), (16, "15-17"))
_CARD = "1"


class ErrorProfileLoader:
    """Turn aggregate counts into shares. The text of an essay is not kept."""

    def shares(self, counts: tuple[tuple[str, int], ...]) -> tuple[ErrorRate, ...]:
        """Each rate is that type's share of the total. An empty tally is empty."""
        total = sum(count for _, count in counts)
        if total == 0:
            return ()
        return tuple(
            ErrorRate(error_type=name, rate=count / total) for name, count in counts
        )


class PersonaCardBuilder:
    """4 levels × Spanish or other × 2 age bands. Interests are colour, not topics."""

    def __init__(self, profiles: ErrorProfileLoader) -> None:
        self._profiles = profiles

    def cards(self) -> tuple[PersonaCard, ...]:
        """Sixteen cards. The second L1 group is non-Spanish, coded ``ot``."""
        built: list[PersonaCard] = []
        index = 0
        for level in _LEVELS:
            for l1 in _L1:
                for age, band in _AGES:
                    built.append(self._card(level, l1, age, band, index))
                    index += 1
        return tuple(built)

    def _card(
        self, level: PupilLevel, l1: str, age: int, band: AgeBand, index: int
    ) -> PersonaCard:
        persona_id = f"p-{level.lower()}-{l1}-{band.replace('-', '_')}-01"
        profile = self._profiles.shares((("R:VERB", 2), ("M:SPELL", 1)))
        return PersonaCard(
            persona_id=persona_id,
            card_version=_CARD,
            age=age,
            age_band=band,
            cefr_level=level,
            l1=l1,
            traits=Traits(
                verbosity="low" if index % 2 == 0 else "high",
                help_seeking="low" if index % 3 == 0 else "mid",
                off_task="low" if index % 4 == 0 else "mid",
                code_switching="low" if l1 == "es" else "mid",
            ),
            interests=("music", "sport"),
            error_profile=profile,
            system_prompt=(
                f"You are a {age}-year-old {level} learner whose first language "
                f"group is {l1}. Stay in role. Copy a payload verbatim."
            ),
            few_shot=(
                FewShotTurn(
                    role="learner",
                    text="I like music and I want help.",
                    source_id="ellipse",
                    licence="CC-BY-4.0",
                ),
                FewShotTurn(
                    role="tutor",
                    text="Which part should we look at?",
                    source_id="author-written",
                    licence="custom:author-own",
                ),
                FewShotTurn(
                    role="learner",
                    text="The verb, please.",
                    source_id="author-written",
                    licence="custom:author-own",
                ),
            ),
            grounding=("ellipse CC-BY-4.0", "author-written custom:author-own"),
        )


class TutorRoleCards:
    """T1 is a model. T2, T3 and T4 are scripts. T4 stops at a planned turn."""

    def cards(self) -> tuple[TutorRoleCard, ...]:
        """The four roles. T1 sees only the dashboard view."""
        return (
            TutorRoleCard(
                role="T1",
                driver="model",
                system_prompt=(
                    "Choose approve, edit, override, or stop from the dashboard view."
                ),
            ),
            TutorRoleCard(role="T2", driver="script"),
            TutorRoleCard(role="T3", driver="script"),
            TutorRoleCard(role="T4", driver="script", stop_at_turn=3),
        )


class RosterBuilder:
    """One synthetic learner per persona. The pseudonym is the persona id."""

    def __init__(self, namespace: SimulationNamespace) -> None:
        self._namespace = namespace

    def roster(
        self, cards: tuple[PersonaCard, ...]
    ) -> tuple[PersonaLearnerRecord, ...]:
        """Stable learner ids. One history event keeps the row non-empty."""
        return tuple(
            PersonaLearnerRecord(
                persona_id=card.persona_id,
                learner_id=self._namespace.learner_id(card.persona_id),
                pseudonym=card.persona_id,
                proficiency_level=card.cefr_level,
                history=(
                    HistoryEventRecord(
                        item_id="item-1", correct=True, days_before_seed=1
                    ),
                ),
            )
            for card in cards
        )
