import pytest
from pydantic import ValidationError

from app.schemas.assistant import AssistantAskRequest, ChatMessageCreate
from app.services.assistant_answer_service import (
    answer_text_from_blocks,
    parse_structured_rag_answer,
    validate_human_answer,
    validate_source_coverage,
)
from app.services.local_llm_service import OllamaGenerationError


@pytest.fixture(autouse=True)
async def prepare_test_database():
    """These unit tests do not require the integration-test PostgreSQL fixture."""

    yield


def test_structured_answer_keeps_inline_source_mapping_and_deduplicates_ids():
    blocks = parse_structured_rag_answer(
        """
        {
          "blocks": [
            {
              "kind": "answer",
              "text": "Первый факт.",
              "source_ids": ["chunk-10", "chunk-10", "chunk-11"]
            },
            {
              "kind": "answer",
              "text": "Второй факт.",
              "source_ids": ["chunk-20"]
            }
          ]
        }
        """,
        allowed_source_ids={"chunk-10", "chunk-11", "chunk-20"},
    )

    assert blocks == [
        {
            "text": "Первый факт.",
            "source_ids": ["chunk-10", "chunk-11"],
        },
        {"text": "Второй факт.", "source_ids": ["chunk-20"]},
    ]
    assert answer_text_from_blocks(blocks) == "Первый факт.\n\nВторой факт."


@pytest.mark.parametrize(
    "raw_answer",
    [
        '{"blocks":[{"kind":"answer","text":"Факт.","source_ids":[]}] }',
        '{"blocks":[{"kind":"answer","text":"Факт.","source_ids":["chunk-999"]}] }',
        (
            '{"blocks":[{"kind":"answer","text":"Факт.",'
            '"source_ids":["chunk-10"],"html":"<b>"}] }'
        ),
        (
            '{"blocks":[{"kind":"insufficient","text":"Недостаточно данных.",'
            '"source_ids":["chunk-10"]}] }'
        ),
    ],
)
def test_structured_answer_rejects_missing_unknown_or_extra_source_data(raw_answer):
    with pytest.raises(OllamaGenerationError):
        parse_structured_rag_answer(
            raw_answer,
            allowed_source_ids={"chunk-10"},
        )


def test_structured_answer_allows_empty_sources_for_insufficient_information():
    blocks = parse_structured_rag_answer(
        (
            '{"blocks":[{"kind":"insufficient",'
            '"text":"Недостаточно информации; уточните вопрос.","source_ids":[]}]}'
        ),
        allowed_source_ids={"chunk-10"},
    )

    assert blocks == [
        {
            "text": "Недостаточно информации; уточните вопрос.",
            "source_ids": [],
        }
    ]


def test_structured_answer_rejects_overcitation_in_one_semantic_block():
    with pytest.raises(OllamaGenerationError, match="слишком много ссылок"):
        parse_structured_rag_answer(
            (
                '{"blocks":[{"kind":"answer","text":"Один конкретный факт.",'
                '"source_ids":["chunk-1","chunk-2","chunk-3","chunk-4"]}]}'
            ),
            allowed_source_ids={"chunk-1", "chunk-2", "chunk-3", "chunk-4"},
        )


def test_detail_level_defaults_to_full_source_coverage_for_both_request_types():
    assert AssistantAskRequest(question="Что найдено?").detail_percent == 100
    assert ChatMessageCreate(content="Что найдено?").detail_percent == 100


@pytest.mark.parametrize(
    "request_type, text_field",
    [
        (AssistantAskRequest, "question"),
        (ChatMessageCreate, "content"),
    ],
)
def test_assistant_request_accepts_at_most_six_sources(request_type, text_field):
    assert request_type(**{text_field: "Что найдено?", "limit": 6}).limit == 6

    with pytest.raises(ValidationError):
        request_type(**{text_field: "Что найдено?", "limit": 7})


@pytest.mark.parametrize(
    "request_type, text_field",
    [
        (AssistantAskRequest, "question"),
        (ChatMessageCreate, "content"),
    ],
)
def test_detail_level_cannot_be_lower_than_eighty_percent(request_type, text_field):
    with pytest.raises(ValidationError):
        request_type(**{text_field: "Что найдено?", "detail_percent": 79})


def test_source_coverage_accepts_four_of_five_sources_at_eighty_percent():
    validate_source_coverage(
        [
            {
                "text": "Подробный ответ.",
                "source_ids": ["chunk-1", "chunk-2", "chunk-3", "chunk-4"],
            }
        ],
        allowed_source_ids={
            "chunk-1",
            "chunk-2",
            "chunk-3",
            "chunk-4",
            "chunk-5",
        },
        detail_percent=80,
    )


def test_source_coverage_rejects_less_than_requested_share():
    with pytest.raises(OllamaGenerationError, match="80%"):
        validate_source_coverage(
            [
                {
                    "text": "Неполный ответ.",
                    "source_ids": ["chunk-1", "chunk-2", "chunk-3"],
                }
            ],
            allowed_source_ids={
                "chunk-1",
                "chunk-2",
                "chunk-3",
                "chunk-4",
                "chunk-5",
            },
            detail_percent=80,
        )


def test_source_coverage_allows_explicit_insufficient_answer():
    validate_source_coverage(
        [{"text": "Недостаточно информации.", "source_ids": []}],
        allowed_source_ids={"chunk-1", "chunk-2"},
        detail_percent=80,
    )


def test_human_answer_validation_allows_useful_scientific_numbers_and_terms():
    validate_human_answer(
        [
            {
                "text": (
                    "Возраст циркона составляет 250 млн лет, "
                    "а содержание SiO2 — около 65 %."
                ),
                "source_ids": ["chunk-10"],
            }
        ],
        expected_language="ru",
    )


@pytest.mark.parametrize(
    "text",
    [
        "The answer is based on the selected publication.",
        "Результаты приведены в работе Gladкochуб и соавторов.",
        (
            "Для более детального представления см. в следующих источниках: "
            "Иванов и др., 2005; Петров и др., 2009."
        ),
        "Магматизм описан в chunk-7, similarity: 0.91.",
        "Ответ #### ����.",
        "Ответ ааааааа 111111.",
        "В найденном фрагменте указано, что возраст составляет 250 млн лет.",
    ],
)
def test_human_answer_validation_rejects_wrong_language_and_service_noise(text):
    with pytest.raises(OllamaGenerationError):
        validate_human_answer(
            [{"text": text, "source_ids": ["chunk-10"]}],
            expected_language="ru",
        )


def test_human_answer_validation_allows_bibliography_when_user_requested_it():
    validate_human_answer(
        [
            {
                "text": (
                    "Литература: Иванов и др., 2005; Петров и др., 2009."
                ),
                "source_ids": ["chunk-10"],
            }
        ],
        expected_language="ru",
        allow_bibliography=True,
    )
