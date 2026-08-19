from app.sources.base import BaseSourceAdapter
from app.sources.guardian import GuardianAdapter
from app.sources.reddit import RedditAdapter
from app.sources.wikipedia import WikipediaAdapter


class SourceRegistry:
    """Maps source names to adapter instances.

    Adding a new source = instantiate its adapter and register it here.
    The search pipeline and API layer only talk to the registry.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, BaseSourceAdapter] = {}

    def register(self, name: str, adapter: BaseSourceAdapter) -> None:
        self._adapters[name] = adapter

    def get(self, name: str) -> BaseSourceAdapter | None:
        return self._adapters.get(name)

    def names(self) -> list[str]:
        return sorted(self._adapters)


registry = SourceRegistry()
registry.register("wikipedia", WikipediaAdapter())
registry.register("guardian", GuardianAdapter())
registry.register("reddit", RedditAdapter())