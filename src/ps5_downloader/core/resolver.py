from __future__ import annotations

from .models import PluginResult, PluginResultType
from .utils import actionable_urls_from_text, normalize_url
from ps5_downloader.plugins.registry import PluginRegistry


class LinkResolver:
    def __init__(self, registry: PluginRegistry | None = None, max_depth: int = 3, max_results: int = 128) -> None:
        self.registry = registry or PluginRegistry()
        self.max_depth = max_depth
        self.max_results = max_results

    def parse_text(self, text: str) -> list[str]:
        return actionable_urls_from_text(text)

    def resolve_url(self, url: str) -> PluginResult:
        return self.registry.resolve(normalize_url(url))

    def grab_url(self, url: str) -> list[PluginResult]:
        seen: set[str] = set()
        results: list[PluginResult] = []
        self._expand_url(url, self.max_depth, seen, results)
        return results

    def resolve_text(self, text: str) -> list[PluginResult]:
        seen: set[str] = set()
        results: list[PluginResult] = []
        for url in self.parse_text(text):
            self._expand_url(url, self.max_depth, seen, results)
            if len(results) >= self.max_results:
                break
        return results

    def _expand_url(self, url: str, depth: int, seen: set[str], results: list[PluginResult]) -> None:
        if len(results) >= self.max_results:
            return
        try:
            normalized = normalize_url(url)
        except ValueError as exc:
            results.append(PluginResult(type=PluginResultType.ERROR, original_url=url, plugin="resolver", message=str(exc)))
            return
        if normalized in seen:
            return
        seen.add(normalized)
        self._expand_result(self.resolve_url(normalized), depth, seen, results)

    def _expand_result(
        self, result: PluginResult, depth: int, seen: set[str], results: list[PluginResult]
    ) -> None:
        if len(results) >= self.max_results:
            return
        if depth > 0 and result.type == PluginResultType.REDIRECT and result.resolved_url:
            self._expand_url(result.resolved_url, depth - 1, seen, results)
            return
        if depth > 0 and result.type == PluginResultType.PACKAGE:
            for child in result.children:
                child_url = child.resolved_url or child.original_url
                if child_url:
                    self._expand_result(child, depth - 1, seen, results)
                if len(results) >= self.max_results:
                    break
            if not result.children:
                results.append(result)
            return
        results.append(result)
