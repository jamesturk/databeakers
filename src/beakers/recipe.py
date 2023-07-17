import typer
import inspect
import sqlite3
import asyncio
import networkx  # type: ignore
from collections import defaultdict, Counter
from typing import Iterable, Callable, Type
from pydantic import BaseModel, ConfigDict
from structlog import get_logger

from .beakers import Beaker, SqliteBeaker, TempBeaker
from .exceptions import SeedError

log = get_logger()


class Transform(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    transform_func: Callable
    error_map: dict[tuple, str]


class Seed(BaseModel):
    name: str
    num_items: int = 0
    imported_at: str | None = None

    def __str__(self):
        if self.imported_at:
            return (
                f"{self.name} ({self.num_items} items imported at {self.imported_at})"
            )
        else:
            return f"{self.name}"


class ErrorType(BaseModel):
    item: BaseModel
    exception: str
    exc_type: str


def if_cond_true(data_cond_tup: tuple[dict, bool]) -> dict | None:
    return data_cond_tup[0] if data_cond_tup[1] else None


def if_cond_false(data_cond_tup: tuple[dict, bool]) -> dict | None:
    return data_cond_tup[0] if not data_cond_tup[1] else None


class Recipe:
    def __init__(self, name: str, db_name: str = "beakers.db"):
        self.name = name
        self.graph = networkx.DiGraph()
        self.beakers: dict[str, Beaker] = {}
        self.seeds: dict[str, tuple[str, Callable[[], Iterable[BaseModel]]]] = {}
        self.db = sqlite3.connect(db_name)
        cursor = self.db.cursor()
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS _seeds (
                name TEXT, 
                beaker_name TEXT,
                num_items INTEGER,
                imported_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )"""
        )

    def __repr__(self) -> str:
        return f"Recipe({self.name})"

    # section: graph ##########################################################

    def add_beaker(
        self,
        name: str,
        datatype: Type[BaseModel],
        # beaker_type: Type[Beaker] = SqliteBeaker,
    ) -> Beaker:
        self.graph.add_node(name, datatype=datatype)
        if datatype is None:
            self.beakers[name] = TempBeaker(name, datatype, self)
        else:
            self.beakers[name] = SqliteBeaker(name, datatype, self)
        return self.beakers[name]

    def add_transform(
        self,
        from_beaker: str,
        to_beaker: str,
        transform_func: Callable,
        *,
        name: str | None = None,
        error_map: dict[tuple, str] | None = None,
    ) -> None:
        if name is None:
            name = transform_func.__name__
            if name == "<lambda>":
                name = "λ"
        transform = Transform(
            name=name,
            transform_func=transform_func,
            error_map=error_map or {},
        )
        self.graph.add_edge(
            from_beaker,
            to_beaker,
            transform=transform,
        )

    def add_conditional(
        self,
        from_beaker: str,
        condition_func: Callable,
        if_true: str,
        if_false: str = "",
    ) -> None:
        # first add a transform to evaluate the conditional
        if condition_func.__name__ == "<lambda>":
            cond_name = f"cond-{from_beaker}"
        else:
            cond_name = f"cond-{from_beaker}-{condition_func.__name__}"
        self.add_beaker(cond_name, None)
        self.add_transform(
            from_beaker,
            cond_name,
            lambda data: (data, condition_func(data)),
            name=cond_name,
        )

        # then add two filtered paths that remove the condition result
        self.add_beaker(if_true, None)
        self.add_transform(
            cond_name,
            if_true,
            if_cond_true,
        )
        if if_false:
            self.add_transform(
                cond_name,
                if_false,
                if_cond_false,
            )

    # section: seeds ##########################################################

    def add_seed(
        self,
        seed_name: str,
        beaker_name: str,
        seed_func: Callable[[], Iterable[BaseModel]],
    ) -> None:
        self.seeds[seed_name] = (beaker_name, seed_func)

    def list_seeds(self) -> dict[str, list[str]]:
        by_beaker = defaultdict(list)
        for seed_name, (beaker_name, _) in self.seeds.items():
            seed = self._db_get_seed(seed_name)
            if not seed:
                seed = Seed(name=seed_name)
            by_beaker[beaker_name].append(seed)
        return dict(by_beaker)

    def _db_get_seed(self, seed_name: str) -> Seed | None:
        cursor = self.db.cursor()
        cursor.row_factory = sqlite3.Row
        cursor.execute("SELECT * FROM _seeds WHERE name = ?", (seed_name,))
        if row := cursor.fetchone():
            return Seed(**row)
        else:
            return None

    def run_seed(self, seed_name: str) -> None:
        try:
            beaker_name, seed_func = self.seeds[seed_name]
        except KeyError:
            raise SeedError(f"Seed {seed_name} not found")
        beaker = self.beakers[beaker_name]

        if seed := self._db_get_seed(seed_name):
            raise SeedError(f"{seed_name} already run at {seed.imported_at}")

        log.info("run_seed", seed_name=seed_name, beaker_name=beaker_name)
        num_items = 0
        for item in seed_func():
            beaker.add_item(item)
            num_items += 1

        cursor = self.db.cursor()
        cursor.execute(
            "INSERT INTO _seeds (name, beaker_name, num_items) VALUES (?, ?, ?)",
            (seed_name, beaker_name, num_items),
        )
        self.db.commit()

    # section: commands #######################################################

    def reset(self) -> None:
        with self.db:
            cursor = self.db.cursor()
            cursor.execute("DELETE FROM _seeds")
            typer.secho("seeds reset", fg=typer.colors.RED)
            for beaker in self.beakers.values():
                if bl := len(beaker):
                    beaker.reset()
                    typer.secho(f"{beaker.name} reset ({bl})", fg=typer.colors.RED)
                else:
                    typer.secho(f"{beaker.name} empty", fg=typer.colors.GREEN)

    def show(self) -> None:
        seed_count = Counter(self.seeds.keys())
        typer.secho("Seeds", fg=typer.colors.GREEN)
        for beaker, count in seed_count.items():
            typer.secho(f"  {beaker} ({count})", fg=typer.colors.GREEN)
        graph_data = self.graph_data()
        for node in graph_data:
            if node["temp"]:
                typer.secho(node["name"], fg=typer.colors.CYAN)
            else:
                typer.secho(
                    f"{node['name']} ({node['len']})",
                    fg=typer.colors.GREEN if node["len"] else typer.colors.YELLOW,
                )
            for edge in node["edges"]:
                typer.secho(f"  -({edge['transform'].name})-> {edge['to_beaker']}")
                for k, v in edge["transform"].error_map.items():
                    if isinstance(k, tuple):
                        typer.secho(
                            f"    {' '.join(c.__name__ for c in k)} -> {v}",
                            fg=typer.colors.RED,
                        )
                    else:
                        typer.secho(f"    {k.__name__} -> {v}", fg=typer.colors.RED)

    def graph_data(self) -> list[dict]:
        nodes = {}

        for node in networkx.topological_sort(self.graph):
            beaker = self.beakers[node]

            nodes[node] = {
                "name": node,
                "temp": isinstance(beaker, TempBeaker),
                "len": len(beaker),
                "edges": [],
            }

            rank = 0
            for from_b, to_b, edge in self.graph.in_edges(node, data=True):
                if nodes[from_b]["rank"] > rank:
                    rank = nodes[from_b]["rank"]
            nodes[node]["rank"] = rank + 1

            for from_b, to_b, edge in self.graph.out_edges(node, data=True):
                edge["to_beaker"] = to_b
                nodes[node]["edges"].append(edge)

        # all data collected for display
        return sorted(nodes.values(), key=lambda x: (x["rank"], x["name"]))

    # section: running ########################################################

    def run_once(
        self, start_beaker: str | None = None, end_beaker: str | None = None
    ) -> None:
        log.info("run_once", recipe=self)
        loop = asyncio.get_event_loop()

        started = False if start_beaker else True

        # go through each node in forward order, pushing data
        for node in networkx.topological_sort(self.graph):
            # only process nodes between start and end
            if not started:
                if node == start_beaker:
                    started = True
                    log.info("partial run start", node=node)
                else:
                    log.info("partial run skip", node=node, waiting_for=start_beaker)
                    continue
            if end_beaker and node == end_beaker:
                log.info("partial run end", node=node)
                break

            # get outbound edges
            edges = self.graph.out_edges(node, data=True)

            for from_b, to_b, edge in edges:
                transform = edge["transform"]

                from_beaker = self.beakers[from_b]
                to_beaker = self.beakers[to_b]
                already_processed = from_beaker.id_set() & to_beaker.id_set()

                log.info(
                    "transform",
                    from_b=from_b,
                    to_b=to_b,
                    to_process=len(from_beaker) - len(already_processed),
                    already_processed=len(already_processed),
                    transform=edge["transform"].name,
                )

                # convert coroutine to function
                if inspect.iscoroutinefunction(transform.transform_func):

                    def t_func(x):
                        return loop.run_until_complete(transform.transform_func(x))

                else:
                    t_func = transform.transform_func

                for id, item in from_beaker.items():
                    if id in already_processed:
                        continue
                    try:
                        transformed = t_func(item)
                        if transformed:
                            to_beaker.add_item(transformed, id)
                    except Exception as e:
                        for (
                            error_types,
                            error_beaker_name,
                        ) in transform.error_map.items():
                            if isinstance(e, error_types):
                                error_beaker = self.beakers[error_beaker_name]
                                error_beaker.add_item(
                                    ErrorType(
                                        item=item,
                                        exception=str(e),
                                        exc_type=str(type(e)),
                                    ),
                                    id,
                                )
                                break
                        else:
                            # no error handler, re-raise
                            raise
