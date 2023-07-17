from beakers import Recipe
from beakers.recipe import Transform
from testdata import Word


def capitalized(word: Word) -> Word:
    return Word(word=word.word.capitalize())


def test_recipe_repr() -> None:
    recipe = Recipe("test")
    assert repr(recipe) == "Recipe(test)"


def test_add_beaker_simple() -> None:
    recipe = Recipe("test")
    recipe.add_beaker("word", Word)
    assert recipe.beakers["word"].name == "word"
    assert recipe.beakers["word"].model == Word
    assert recipe.beakers["word"].recipe == recipe


def test_add_transform():
    recipe = Recipe("test")
    recipe.add_beaker("word", Word)
    recipe.add_transform("word", "capitalized", capitalized)
    assert recipe.graph["word"]["capitalized"]["transform"] == Transform(
        name="capitalized", transform_func=capitalized, error_map={}
    )


def test_add_transform_lambda():
    recipe = Recipe("test")
    recipe.add_beaker("word", Word)
    recipe.add_transform("word", "capitalized", lambda x: x)
    assert recipe.graph["word"]["capitalized"]["transform"].name == "λ"


def test_add_transform_error_map():
    recipe = Recipe("test")
    recipe.add_beaker("word", Word)
    recipe.add_transform(
        "word", "capitalized", capitalized, error_map={(ValueError,): "error"}
    )
    assert recipe.graph["word"]["capitalized"]["transform"].error_map == {
        (ValueError,): "error"
    }


# def test_add_conditional_simple():
#     recipe = Recipe("test")
#     recipe.add_beaker("word", Word)
#     recipe.add_conditional("word", "capitalized", lambda x: True)
#     assert recipe.graph["word"]["capitalized"]["conditional"].name == "λ"


def test_graph_data_simple():
    r = Recipe("test")
    r.add_beaker("word", Word)
    r.add_beaker("capitalized", Word)
    r.add_beaker("filtered", Word)
    r.add_transform("word", "capitalized", capitalized)
    r.add_transform(
        "capitalized", "filtered", lambda x: x if x.word.startswith("A") else None
    )
    gd = r.graph_data()
    assert len(gd) == 3
    assert gd[0] == {
        "len": 0,
        "name": "word",
        "rank": 1,
        "temp": False,
        "edges": [
            {
                "to_beaker": "capitalized",
                "transform": Transform(
                    name="capitalized", transform_func=capitalized, error_map={}
                ),
            }
        ],
    }
    assert gd[1]["len"] == 0
    assert gd[1]["name"] == "capitalized"
    assert gd[1]["rank"] == 2
    assert gd[1]["temp"] is False
    assert gd[1]["edges"][0]["to_beaker"] == "filtered"
    assert gd[1]["edges"][0]["transform"].name == "λ"
    assert gd[2] == {
        "len": 0,
        "name": "filtered",
        "rank": 3,
        "temp": False,
        "edges": [],
    }


def test_graph_data_multiple_rank():
    r = Recipe("test")
    r.add_beaker("nouns", Word)
    r.add_beaker("verbs", Word)
    r.add_beaker("normalized", Word)
    r.add_beaker("english", Word)
    r.add_beaker("spanish", Word)
    r.add_transform("nouns", "normalized", lambda x: x)
    r.add_transform("verbs", "normalized", lambda x: x)
    r.add_transform("normalized", "english", lambda x: x)
    r.add_transform("normalized", "spanish", lambda x: x)
    gd = r.graph_data()
    assert len(gd) == 5
    assert gd[0]["name"] == "nouns"
    assert gd[0]["rank"] == 1
    assert gd[1]["name"] == "verbs"
    assert gd[1]["rank"] == 1
    assert gd[2]["name"] == "normalized"
    assert gd[2]["rank"] == 2
    assert gd[3]["name"] == "english"
    assert gd[3]["rank"] == 3
    assert gd[4]["name"] == "spanish"
    assert gd[4]["rank"] == 3