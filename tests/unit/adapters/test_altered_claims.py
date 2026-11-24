"""An altered vetted sentence is held; an original explanation is only flagged.

Support counts a sentence when a retrieved passage states it word for word.
A sentence that *contains* a vetted sentence but is not that sentence ("It
is false that hola means hello") alters vetted content. Drift holds it.
A sentence the sources do not mention at all stays unsupported and flagged
for the tutor, but does not pause the turn (DEC-0005, amended 2026-11-19).
"""

import pytest
from pydantic import ValidationError
from tests.support.samples import Samples
from tests.unit.domain.test_output_gates import OutputGates

from tutor_api.adapters.checks.source_support import (
    SentenceSourceSupport,
    SentenceSplitter,
)
from tutor_api.prototype import PrototypeCopy
from tutor_core.domain.audit.record_hash import AuditRecordHash
from tutor_core.domain.models.retrieval import Snippet
from tutor_core.domain.models.safety import ClaimSpan, SourceSupportReport
from tutor_core.domain.models.turn import TurnState


def _snippet(content: str) -> Snippet:
    return Samples().snippet().model_copy(update={"content": content})


def _verify(
    draft: str, vetted: str = "Hola means hello in Spanish."
) -> SourceSupportReport:
    return SentenceSourceSupport(SentenceSplitter()).verify(draft, (_snippet(vetted),))


class TestAlteredClaims:
    def test_a_negated_vetted_sentence_is_altered(self) -> None:
        report = _verify("It is false that Hola means hello in Spanish.")
        assert report.supported == ()
        assert len(report.unsupported) == 1
        assert [s.text for s in report.altered] == [s.text for s in report.unsupported]
        assert report.altered[0].source_ids == ("kb://greetings",)

    def test_a_vetted_sentence_with_words_added_is_altered(self) -> None:
        report = _verify("Hola means hello in Spanish only at night.")
        assert report.altered != ()

    def test_an_original_explanation_is_unsupported_but_not_altered(self) -> None:
        report = _verify("Verbs are words that show an action. I kick the ball.")
        assert len(report.unsupported) == 2
        assert report.altered == ()

    def test_the_vetted_sentence_itself_is_supported_not_altered(self) -> None:
        report = _verify("Hola means hello in Spanish.")
        assert len(report.supported) == 1
        assert report.altered == ()

    def test_a_vetted_sentence_must_appear_as_whole_words(self) -> None:
        report = _verify("Chola means hello in Spanish class.", "Hola means hello.")
        assert report.altered == ()

    def test_a_one_word_vetted_sentence_alters_nothing(self) -> None:
        report = _verify("Hello there, my friend.", "Hello.")
        assert report.altered == ()

    def test_an_altered_span_must_be_an_unsupported_span(self) -> None:
        stray = ClaimSpan(text="elsewhere", start=0, end=9)
        with pytest.raises(ValidationError, match="altered"):
            SourceSupportReport(
                supported=(), unsupported=(), support_ratio=1.0, altered=(stray,)
            )


class TestRecordHash:
    def _record(self, altered: tuple[ClaimSpan, ...]):  # type: ignore[no-untyped-def]
        span = Samples().unsupported_span()
        support = SourceSupportReport(
            supported=(Samples().supported_span(),),
            unsupported=(span,),
            support_ratio=0.5,
            altered=altered,
        )
        return Samples().audit_record().model_copy(update={"source_support": support})

    def test_a_report_without_altered_spans_hashes_as_before(self) -> None:
        canonical = AuditRecordHash().canonical(self._record(()))
        assert '"altered"' not in canonical

    def test_altered_spans_are_covered_by_the_hash(self) -> None:
        hasher = AuditRecordHash()
        altered = self._record((Samples().unsupported_span(),))
        assert '"altered"' in hasher.canonical(altered)
        assert hasher.digest(altered) != hasher.digest(self._record(()))


def _turn(altered: bool) -> TurnState:
    turn = Samples().turn()
    assert turn.generated is not None
    span = Samples().unsupported_span()
    turn.generated = turn.generated.model_copy(
        update={
            "support": SourceSupportReport(
                supported=(),
                unsupported=(span,),
                support_ratio=0.0,
                altered=(span,) if altered else (),
            )
        }
    )
    return turn


class TestDrift:
    def _prototype(self):  # type: ignore[no-untyped-def]
        copy = PrototypeCopy()
        return OutputGates().drift(
            envelope=copy.drift_envelope(), session=copy.session_envelope()
        )

    def test_the_prototype_holds_any_altered_sentence(self) -> None:
        assert PrototypeCopy().drift_envelope().max_altered_claims == 0

    async def test_an_altered_sentence_pauses_drift(self) -> None:
        verdict = await self._prototype().evaluate(_turn(altered=True))
        assert verdict.decision == "pause"

    async def test_an_unsupported_original_sentence_passes_drift(self) -> None:
        verdict = await self._prototype().evaluate(_turn(altered=False))
        assert verdict.decision == "pass"

    async def test_an_envelope_without_the_bound_ignores_altered_sentences(
        self,
    ) -> None:
        verdict = await OutputGates().drift().evaluate(_turn(altered=True))
        assert OutputGates().loose().max_altered_claims is None
        assert verdict.decision == "pass"
