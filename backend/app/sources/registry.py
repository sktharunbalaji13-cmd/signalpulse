from app.sources.arxiv import ArxivAdapter
from app.sources.base import BaseSourceAdapter
from app.sources.guardian import GuardianAdapter
from app.sources.hacker_news import HackerNewsAdapter
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

    def adapters(self) -> list[BaseSourceAdapter]:
        """All registered adapter instances (not only the configured ones)."""
        return list(self._adapters.values())

    def has_enabled(self) -> bool:
        """M21.3: at least one registered adapter is configured to run."""
        return any(adapter.is_configured() for adapter in self._adapters.values())


registry = SourceRegistry()
registry.register("wikipedia", WikipediaAdapter())
registry.register("guardian", GuardianAdapter())
registry.register("reddit", RedditAdapter())
registry.register("hacker_news", HackerNewsAdapter())
registry.register("arxiv", ArxivAdapter())
# GDELT adapter exists (app.sources.gdelt) and is fully tested offline, but
# it is deliberately NOT registered: the M2-C gate evaluation was a NO-GO
# (see docs/ADR/0005-gdelt-gate.md). Re-enable with one line if the
# decision is revisited.