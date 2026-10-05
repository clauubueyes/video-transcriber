import io
import json
import urllib.error
from unittest.mock import Mock

import pytest

from app.services.recipe_extractor import (
    GroqRecipeExtractor,
    RecipeExtractionError,
    extraction_schema,
)


def recipe_data(**changes):
    return {
        "recipeFound": True, "title": "Tortilla de patatas",
        "description": "Tortilla con patatas y huevos.",
        "ingredients": [
            {"item": "Patatas", "amount": "500 g"},
            {"item": "Huevos", "amount": "4"},
            {"item": "Sal", "amount": ""},
        ],
        "steps": [
            {"order": 1, "instruction": "Pelar y freír las patatas."},
            {"order": 2, "instruction": "Batir los huevos y cuajar la tortilla."},
        ],
        "tags": ["Plato Principal"], "prepTimeMinutes": None, "servings": None,
        "notes": ["La cantidad de sal no se menciona."], **changes,
    }


def groq_response(recipe=None, **choice_changes):
    return io.BytesIO(json.dumps({"choices": [{
        "finish_reason": "stop",
        "message": {"content": json.dumps(recipe or recipe_data())},
        **choice_changes,
    }]}).encode())


def test_extracts_a_structured_recipe_with_secret_only_in_server_header():
    opener = Mock(return_value=groq_response())
    extractor = GroqRecipeExtractor("private-api-key", opener=opener)
    recipe = extractor.extract("Hoy haremos tortilla. Necesitamos 500 g de patatas.")

    request = opener.call_args.args[0]
    payload = json.loads(request.data)
    assert request.get_header("Authorization") == "Bearer private-api-key"
    assert "private-api-key" not in request.data.decode()
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert json.loads(payload["messages"][1]["content"])["transcription"].startswith(
        "Hoy haremos tortilla",
    )
    assert recipe.ingredients[2].amount == ""
    assert recipe.prep_time_minutes is None
    assert recipe.servings is None
    assert recipe.model_dump(by_alias=True)["recipeFound"] is True


def test_strict_schema_preserves_the_title_property_and_requires_nullable_fields():
    schema = extraction_schema()
    assert "title" in schema["properties"]
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["additionalProperties"] is False
    for nested in schema["$defs"].values():
        assert nested["additionalProperties"] is False
        assert set(nested["required"]) == set(nested["properties"])


def test_reorders_steps_and_strips_whitespace():
    data = recipe_data(steps=[
        {"order": 3, "instruction": " Cortar. "},
        {"order": 3, "instruction": " Cocinar. "},
    ])
    recipe = GroqRecipeExtractor(
        "key", opener=Mock(return_value=groq_response(data)),
    ).extract("Cortar y cocinar.")
    assert [step.order for step in recipe.steps] == [1, 2]
    assert recipe.steps[0].instruction == "Cortar."


@pytest.mark.parametrize("status, expected", [(401, 503), (403, 503), (429, 429),
                                             (500, 502), (400, 502)])
def test_provider_errors_do_not_expose_payload_or_credentials(status, expected):
    opener = Mock(side_effect=urllib.error.HTTPError(
        "https://api.groq.com", status, "private transcript and key", {},
        io.BytesIO(b"private transcript and key"),
    ))
    with pytest.raises(RecipeExtractionError) as raised:
        GroqRecipeExtractor("private-key", opener=opener).extract("Secret transcript")
    assert raised.value.status_code == expected
    assert "private" not in str(raised.value)
    assert "Secret transcript" not in str(raised.value)


@pytest.mark.parametrize("changes", [
    {"ingredients": []}, {"steps": []}, {"servings": 0}, {"title": ""},
    {"servings": "4"}, {"unknown": "field"},
])
def test_rejects_incomplete_or_invalid_recipes(changes):
    with pytest.raises(RecipeExtractionError, match="inválida"):
        GroqRecipeExtractor("key", opener=Mock(
            return_value=groq_response(recipe_data(**changes)),
        )).extract("A recipe")


def test_rejects_truncated_output_instead_of_using_a_partial_recipe():
    with pytest.raises(RecipeExtractionError, match="completado"):
        GroqRecipeExtractor("key", opener=Mock(return_value=groq_response(
            finish_reason="length",
        ))).extract("A recipe")


def test_non_recipe_text_is_explicit_and_not_fabricated():
    data = recipe_data(
        recipeFound=False, title="", description="", ingredients=[], steps=[],
        tags=[], notes=["No se explica ninguna elaboración."],
    )
    result = GroqRecipeExtractor(
        "key", opener=Mock(return_value=groq_response(data)),
    ).extract("Bienvenidos a nuestro canal de viajes.")
    assert result.recipe_found is False
    assert result.ingredients == []


def test_empty_or_oversized_input_never_calls_the_provider():
    opener = Mock()
    extractor = GroqRecipeExtractor("key", opener=opener, max_transcript_chars=10)
    for text in (" ", "x" * 11):
        with pytest.raises(RecipeExtractionError) as raised:
            extractor.extract(text)
        assert raised.value.status_code == 422
    opener.assert_not_called()


def test_connection_timeout_has_an_actionable_error():
    with pytest.raises(RecipeExtractionError, match="conectar") as raised:
        GroqRecipeExtractor("key", opener=Mock(side_effect=TimeoutError())).extract(
            "A recipe",
        )
    assert raised.value.status_code == 504
