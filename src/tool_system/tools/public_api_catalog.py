from __future__ import annotations

from typing import Any

from src.connectors.store import save_external_service

from ..context import ToolContext
from ..errors import ToolInputError
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec


# A deliberately small Jonathan-owned starter index.  It is kept in source so
# discovery works offline and does not make the application depend on a remote
# catalog.  Documentation links remain the authority for terms and credentials.
PUBLIC_APIS: tuple[dict[str, str], ...] = (
    {"id": "crossref", "name": "Crossref", "category": "Books & Research", "description": "Search scholarly metadata and DOI records", "auth": "none", "https": "yes", "cors": "yes", "base_url": "https://api.crossref.org", "documentation_url": "https://api.crossref.org/swagger-ui/index.html"},
    {"id": "frankfurter", "name": "Frankfurter", "category": "Finance", "description": "Reference exchange rates published by central banks", "auth": "none", "https": "yes", "cors": "yes", "base_url": "https://api.frankfurter.app", "documentation_url": "https://frankfurter.dev/"},
    {"id": "github", "name": "GitHub REST", "category": "Development", "description": "Repository, issue, release and account APIs", "auth": "bearer", "https": "yes", "cors": "yes", "base_url": "https://api.github.com", "documentation_url": "https://docs.github.com/en/rest"},
    {"id": "nager-date", "name": "Nager.Date", "category": "Calendar", "description": "Public holiday information for supported countries", "auth": "none", "https": "yes", "cors": "yes", "base_url": "https://date.nager.at/api/v3", "documentation_url": "https://date.nager.at/swagger/index.html"},
    {"id": "nasa", "name": "NASA Open APIs", "category": "Science", "description": "NASA imagery and science datasets", "auth": "api_key", "https": "yes", "cors": "unknown", "base_url": "https://api.nasa.gov", "documentation_url": "https://api.nasa.gov/"},
    {"id": "open-meteo", "name": "Open-Meteo", "category": "Weather", "description": "Weather forecasts and historical weather data", "auth": "none", "https": "yes", "cors": "yes", "base_url": "https://api.open-meteo.com/v1", "documentation_url": "https://open-meteo.com/en/docs"},
    {"id": "openalex", "name": "OpenAlex", "category": "Books & Research", "description": "Search scholarly works, authors and institutions", "auth": "none", "https": "yes", "cors": "yes", "base_url": "https://api.openalex.org", "documentation_url": "https://docs.openalex.org/"},
    {"id": "sec-data", "name": "SEC EDGAR Data", "category": "Finance", "description": "United States public-company filing data", "auth": "user_agent", "https": "yes", "cors": "unknown", "base_url": "https://data.sec.gov", "documentation_url": "https://www.sec.gov/search-filings/edgar-application-programming-interfaces"},
    {"id": "usgs-earthquake", "name": "USGS Earthquake", "category": "Science", "description": "Earthquake catalog search and real-time feeds", "auth": "none", "https": "yes", "cors": "yes", "base_url": "https://earthquake.usgs.gov/fdsnws/event/1", "documentation_url": "https://earthquake.usgs.gov/fdsnws/event/1/"},
    {"id": "world-bank", "name": "World Bank Indicators", "category": "Government", "description": "Global development indicators and country data", "auth": "none", "https": "yes", "cors": "yes", "base_url": "https://api.worldbank.org/v2", "documentation_url": "https://datahelpdesk.worldbank.org/knowledgebase/topics/125589-developer-information"},
)


def _matches(item: dict[str, str], query: str, category: str) -> bool:
    if category and item["category"].casefold() != category.casefold():
        return False
    if not query:
        return True
    haystack = " ".join((item["id"], item["name"], item["category"], item["description"]))
    return query.casefold() in haystack.casefold()


class PublicApiCatalogTool:
    READ_ONLY = {"search", "categories", "get"}

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="PublicApiCatalog",
            description=(
                "Discover a small audited starter set of public APIs by category/auth/HTTPS/CORS, "
                "inspect documentation, and add a selected API to Jonathan's connector cards. "
                "Provider terms, quotas and credentials still apply."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": ["search", "categories", "get", "connect"]},
                    "query": {"type": "string"},
                    "category": {"type": "string"},
                    "id": {"type": "string"},
                    "api_key": {"type": "string"},
                    "bearer_token": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "required": ["action"],
            },
            is_destructive=True,
            max_result_size_chars=100_000,
            strict=True,
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        if tool_input.get("action") in self.READ_ONLY:
            return PermissionResult.allow()
        return maybe_ask_for_gated_tool(
            context,
            "PublicApiCatalog",
            f"Add public API connector: {tool_input.get('id') or '(missing id)'}",
            "Allow PublicApiCatalog connector changes for the rest of this session",
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(tool_input["action"])
        if action == "categories":
            counts: dict[str, int] = {}
            for item in PUBLIC_APIS:
                counts[item["category"]] = counts.get(item["category"], 0) + 1
            return ToolResult(name="PublicApiCatalog", output={"categories": counts, "total": len(PUBLIC_APIS)})

        if action == "search":
            query = str(tool_input.get("query") or "").strip()
            category = str(tool_input.get("category") or "").strip()
            limit = int(tool_input.get("limit") or 50)
            items = [dict(item) for item in PUBLIC_APIS if _matches(item, query, category)][:limit]
            return ToolResult(name="PublicApiCatalog", output={"items": items, "count": len(items), "offline_catalog": True})

        api_id = str(tool_input.get("id") or "").strip()
        if not api_id:
            raise ToolInputError("id is required")
        item = next((dict(value) for value in PUBLIC_APIS if value["id"] == api_id), None)
        if item is None:
            raise ToolInputError(f"unknown public API id: {api_id}")
        if action == "get":
            return ToolResult(name="PublicApiCatalog", output={"api": item, "terms_note": "Review the provider documentation, terms, attribution, rate limits and data policy before use."})
        if action == "connect":
            auth = item["auth"]
            if auth == "api_key" and not str(tool_input.get("api_key") or "").strip():
                raise ToolInputError(f"{item['name']} requires api_key")
            auth_type = "api_key" if auth == "api_key" else "bearer" if auth == "bearer" else "none"
            connector = save_external_service(
                name=item["name"],
                base_url=item["base_url"],
                auth_type=auth_type,
                service_id=f"public-api-{item['id']}",
                api_key=tool_input.get("api_key") or "",
                api_key_header="X-API-Key",
                bearer_token=tool_input.get("bearer_token") or "",
            )
            return ToolResult(name="PublicApiCatalog", output={"connected": True, "api": item, "connectors": connector})
        raise ToolInputError(f"unsupported action: {action}")
