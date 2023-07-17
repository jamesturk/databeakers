import importlib
import typer
import sys
from types import SimpleNamespace
from pprint import pprint
from typing import List, Optional
from typing_extensions import Annotated

from beakers.exceptions import SeedError

app = typer.Typer()


def _load_recipe(dotted_path: str) -> SimpleNamespace:
    sys.path.append(".")
    path, name = dotted_path.rsplit(".", 1)
    mod = importlib.import_module(path)
    return getattr(mod, name)


@app.callback()
def main(
    ctx: typer.Context,
    recipe: str = typer.Option(None, envvar="BEAKER_RECIPE"),
) -> None:
    if not recipe:
        typer.secho(
            "Missing recipe; pass --recipe or set env[BEAKER_RECIPE]",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    ctx.obj = _load_recipe(recipe)


@app.command()
def reset(ctx: typer.Context) -> None:
    ctx.obj.reset()


@app.command()
def show(ctx: typer.Context) -> None:
    ctx.obj.show()


@app.command()
def graph(ctx: typer.Context) -> None:
    pprint(ctx.obj.graph_data())


@app.command()
def seeds(ctx: typer.Context) -> None:
    for beaker, seeds in ctx.obj.list_seeds().items():
        typer.secho(beaker)
        for seed in seeds:
            typer.secho(
                f"  {seed}",
                fg=typer.colors.GREEN if seed.num_items else typer.colors.YELLOW,
            )


@app.command()
def seed(ctx: typer.Context, name: str) -> None:
    try:
        ctx.obj.run_seed(name)
    except SeedError as e:
        typer.secho(f"{e}", fg=typer.colors.RED)
        raise typer.Exit(1)


@app.command()
def run(
    ctx: typer.Context,
    input: Annotated[Optional[List[str]], typer.Option(...)] = None,
    start: Optional[str] = typer.Option(None),
    end: Optional[str] = typer.Option(None),
) -> None:
    if ctx.obj.seeds:
        typer.secho("Seeding beakers", fg=typer.colors.GREEN)
        ctx.obj.process_seeds()
    has_data = any(ctx.obj.beakers.values())
    if not input and not has_data:
        typer.secho("No data; pass --input to seed beaker(s)", fg=typer.colors.RED)
        raise typer.Exit(1)
    for input_str in input or []:
        beaker, filename = input_str.split("=")
        ctx.obj.csv_to_beaker(filename, beaker)
    ctx.obj.run_once(start, end)


if __name__ == "__main__":
    app()
