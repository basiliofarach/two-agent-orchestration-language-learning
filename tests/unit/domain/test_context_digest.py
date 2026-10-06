"""The digest that binds a record to the chunk text the model was given."""

from tests.support.samples import Samples

from tutor_core.domain.audit.context_digest import CitedContextDigest


class TestCitedContextDigest:
    def test_the_same_snippets_give_the_same_digest(self) -> None:
        snippets = (Samples().snippet(),)
        assert CitedContextDigest().digest(snippets) == CitedContextDigest().digest(
            snippets
        )
        assert len(CitedContextDigest().digest(snippets)) == 64

    def test_edited_chunk_text_changes_the_digest(self) -> None:
        snippet = Samples().snippet()
        edited = snippet.model_copy(update={"content": "Hola means goodbye."})
        assert CitedContextDigest().digest((snippet,)) != CitedContextDigest().digest(
            (edited,)
        )

    def test_a_changed_review_status_changes_the_digest(self) -> None:
        snippet = Samples().snippet()
        retracted = snippet.model_copy(
            update={
                "source": snippet.source.model_copy(
                    update={"review_status": "retracted"}
                )
            }
        )
        assert CitedContextDigest().digest((snippet,)) != CitedContextDigest().digest(
            (retracted,)
        )

    def test_a_missing_chunk_changes_the_digest(self) -> None:
        snippet = Samples().snippet()
        assert CitedContextDigest().digest((snippet,)) != CitedContextDigest().digest(
            ()
        )

    def test_order_is_part_of_the_digest(self) -> None:
        first = Samples().snippet()
        second = first.model_copy(update={"ordinal": first.ordinal + 1})
        assert CitedContextDigest().digest(
            (first, second)
        ) != CitedContextDigest().digest((second, first))
