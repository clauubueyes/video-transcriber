"""Recetas extraídas de una transcripción, con cantidades opcionales."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RecipeIngredient(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    item: str = Field(min_length=1, max_length=200)
    amount: str = Field(max_length=100)


class RecipeStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    order: int = Field(ge=1)
    instruction: str = Field(min_length=1, max_length=4000)


class ExtractedRecipe(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    recipe_found: bool = Field(alias="recipeFound")
    title: str = Field(max_length=200)
    description: str = Field(max_length=2000)
    ingredients: list[RecipeIngredient] = Field(max_length=100)
    steps: list[RecipeStep] = Field(max_length=100)
    tags: list[str] = Field(max_length=10)
    prep_time_minutes: int | None = Field(alias="prepTimeMinutes", ge=1, le=10080)
    servings: int | None = Field(ge=1, le=1000)
    notes: list[str] = Field(max_length=20)

    @model_validator(mode="after")
    def requires_recipe_content(self) -> Self:
        if self.recipe_found and not (self.title and self.ingredients and self.steps):
            raise ValueError("La receta debe contener título, ingredientes y pasos.")
        for index, step in enumerate(self.steps, start=1):
            step.order = index
        return self
