"""Local embeddings are deterministic and the width the schema indexes."""

import math

import pytest
from tests.contract.test_port_contracts import EmbeddingPortContract

from tutor_api.adapters.llm.local_embedding import LocalEmbedding
from tutor_api.adapters.persistence.schema import BaseSchema
from tutor_core.domain.ports.embedding import EmbeddingPort

_WIDTH = BaseSchema().embedding_dimensions()


class TestLocalEmbeddingContract(EmbeddingPortContract):
    def port(self) -> EmbeddingPort:
        return LocalEmbedding(_WIDTH)


class TestLocalEmbedding:
    def test_the_width_matches_the_schema(self) -> None:
        vector = LocalEmbedding(_WIDTH).embed("library")
        assert len(vector) == _WIDTH

    def test_the_width_is_the_one_injected(self) -> None:
        assert len(LocalEmbedding(8).embed("library")) == 8

    def test_the_same_text_is_the_same_vector(self) -> None:
        embedding = LocalEmbedding(_WIDTH)
        assert embedding.embed("The library") == embedding.embed("The library")

    def test_a_token_vector_is_unit_length(self) -> None:
        vector = LocalEmbedding(_WIDTH).embed("library")
        norm = math.sqrt(sum(item * item for item in vector))
        assert norm == pytest.approx(1.0)

    def test_whitespace_is_a_zero_vector(self) -> None:
        vector = LocalEmbedding(_WIDTH).embed("   ")
        assert set(vector) == {0.0}
