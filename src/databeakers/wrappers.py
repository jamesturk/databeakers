import time
import asyncio
import inspect
import functools
from pydantic import BaseModel
from structlog import get_logger
from ._utils import callable_name

log = get_logger()


def RateLimit(edge_func, requests_per_second=1):
    last_call = None

    @functools.wraps(edge_func)
    async def new_func(item):
        nonlocal last_call
        if last_call is not None:
            diff = (1 / requests_per_second) - (time.time() - last_call)
            if diff > 0:
                log.debug("RateLimit sleep", seconds=diff, last_call=last_call)
                await asyncio.sleep(diff)
        last_call = time.time()
        result = edge_func(item)
        if inspect.isawaitable(result):
            return await result
        return result

    new_func.__name__ = f"RateLimit({callable_name(edge_func)}, {requests_per_second})"
    return new_func


class AdaptiveRateLimit:
    """ """

    def __init__(
        self,
        edge_func,
        timeout_exceptions,
        *,
        requests_per_second=1,
        back_off_rate=2,
        speed_up_after=1,
    ):
        self.edge_func = edge_func
        self.requests_per_second = requests_per_second
        self.desired_requests_per_second = requests_per_second
        self.timeout_exceptions = timeout_exceptions
        self.back_off_rate = back_off_rate
        self.speed_up_after = speed_up_after
        self.successes_counter = 0
        self.last_call = None
        """
        - slow down by factor of back_off_rate on timeout
        - speed up by factor of back_off_rate on speed_up_after success
        """

    def __repr__(self):
        return f"AdaptiveRateLimit({callable_name(self.edge_func)}, {self.requests_per_second})"

    async def __call__(self, item: BaseModel) -> BaseModel:
        if self.last_call is not None:
            diff = (1 / self.requests_per_second) - (time.time() - self.last_call)
            if diff > 0:
                log.debug(
                    "AdaptiveRateLimit sleep",
                    seconds=diff,
                    last_call=self.last_call,
                    streak=self.successes_counter,
                )
                await asyncio.sleep(diff)
        self.last_call = time.time()

        try:
            result = self.edge_func(item)
            if inspect.isawaitable(result):
                result = await result

            # check if we should speed up
            self.successes_counter += 1
            if (
                self.successes_counter >= self.speed_up_after
                and self.requests_per_second < self.desired_requests_per_second
            ):
                self.successes_counter = 0
                self.requests_per_second *= self.back_off_rate
                log.warning(
                    "AdaptiveRateLimit speed up",
                    requests_per_second=self.requests_per_second,
                )

            return result
        except self.timeout_exceptions as e:
            self.requests_per_second /= self.back_off_rate
            log.warning(
                "AdaptiveRateLimit slow down",
                exception=str(e),
                requests_per_second=self.requests_per_second,
            )
            raise e


def Retry(edge_func, retries):
    """
    Retry an edge a number of times.
    """

    @functools.wraps(edge_func)
    async def new_func(item):
        exception = None
        for n in range(retries + 1):
            try:
                return await edge_func(item)
            except Exception as e:
                exception = e
                log.error("Retry", exception=str(e), retry=n + 1, max_retries=retries)
        # if we get here, we've exhausted our retries
        # (conditional appeases mypy)
        if exception:
            raise exception

    new_func.__name__ = f"Retry({callable_name(edge_func)}, {retries})"
    return new_func
