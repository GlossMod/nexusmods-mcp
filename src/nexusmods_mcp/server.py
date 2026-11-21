"""Nexus Mods tools served over MCP stdio."""

import logging
import os
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import Field

from . import queries
from .api import Nexus, NexusError, domain_name, web_url
from .download import download_path, save_archive

Positive = Annotated[int, Field(gt=0, le=2_147_483_647)]
Offset = Annotated[int, Field(ge=0, le=2_147_483_647)]
Count = Annotated[int, Field(ge=1, le=100)]
Direction = Literal["ASC", "DESC"]
ModSort = Literal[
    "updatedAt",
    "createdAt",
    "downloads",
    "uniqueDownloads",
    "endorsements",
    "name",
    "size",
    "relevance",
]
GameSort = Literal["name", "downloads", "mods", "collections", "approved", "relevance"]
FileCategory = Literal[
    "MAIN", "UPDATE", "OPTIONAL", "OLD_VERSION", "MISCELLANEOUS", "REMOVED", "ARCHIVED"
]


def http_client():
    return httpx.AsyncClient(timeout=httpx.Timeout(45, connect=15))


def build_server(client_factory=http_client):
    server = FastMCP("Nexus Mods")

    @server.tool()
    async def find_games(
        name: str = "",
        offset: Offset = 0,
        count: Count = 20,
        sort: GameSort = "name",
        direction: Direction = "ASC",
    ) -> dict[str, Any]:
        """Browse the games directory or search part of a name. Use domainName in subsequent tools."""
        variables = {
            "offset": offset,
            "count": count,
            "sort": [{sort: {"direction": direction}}],
            "filter": {"name": [{"value": name, "op": "WILDCARD"}]} if name else None,
        }
        async with client_factory() as http:
            return (await Nexus(http).gql(queries.GAMES, variables))["games"]

    @server.tool()
    async def find_mods(
        game_domain: str | None = None,
        name: str = "",
        author: str | None = None,
        category: str | None = None,
        tag: str | None = None,
        adult_content: bool | None = None,
        sort: ModSort = "updatedAt",
        direction: Direction = "DESC",
        offset: Offset = 0,
        count: Count = 20,
    ) -> dict[str, Any]:
        """Browse or search mods by game domain, partial name, author, category name, tag and adult flag."""
        filters = {}
        if name:
            filters["name"] = [{"value": name, "op": "WILDCARD"}]
        fields = {
            "gameDomainName": domain_name(game_domain)
            if game_domain is not None
            else None,
            "author": author,
            "categoryName": category,
            "tag": tag,
            "adultContent": adult_content,
        }
        for key, value in fields.items():
            if value is not None:
                filters[key] = [{"value": value, "op": "EQUALS"}]
        variables = {
            "filter": filters or None,
            "offset": offset,
            "count": count,
            "sort": [{sort: {"direction": direction}}],
        }
        async with client_factory() as http:
            page = (await Nexus(http).gql(queries.MODS, variables))["mods"]
        for row in page["nodes"]:
            row["websiteUrl"] = web_url(row["game"]["domainName"], row["modId"])
        return page

    @server.tool()
    async def get_mod(game_domain: str, mod_id: Positive) -> dict[str, Any]:
        """Get Mod details, website, description, uploader, tags, statistics and the native REST gallery."""
        async with client_factory() as http:
            nexus = Nexus(http)
            result = {"websiteUrl": web_url(game_domain, mod_id)}
            missing = {}
            try:
                variables = await nexus.ids(game_domain, mod_id)
                result["mod"] = (await nexus.gql(queries.MOD_DETAILS, variables))["mod"]
            except NexusError as exc:
                missing["graphql"] = str(exc)
            try:
                result["v3"] = await nexus.rest_mod(game_domain, mod_id)
            except NexusError as exc:
                missing["v3"] = str(exc)
            if len(missing) == 2:
                raise NexusError(" / ".join(missing.values()))
            if missing:
                result["unavailable"] = missing
            return result

    @server.tool()
    async def get_requirements(
        game_domain: str,
        mod_id: Positive,
        offset: Offset = 0,
        reverse_offset: Offset = 0,
        count: Count = 20,
        include_disabled_legacy: bool = False,
    ) -> dict[str, Any]:
        """Get Mod and DLC requirements and mods depending on this one. Page each direction independently.

        When legacyModRequirementsEnabled is false use get_file_requirements for a selected release.
        """
        async with client_factory() as http:
            nexus = Nexus(http)
            variables = await nexus.ids(game_domain, mod_id)
            variables.update(
                offset=offset,
                reverseOffset=reverse_offset,
                count=count,
                skipDisabled=not include_disabled_legacy,
            )
            return (await nexus.gql(queries.REQUIREMENTS, variables))["mod"]

    @server.tool()
    async def get_file_requirements(
        game_domain: str, mod_id: Positive, file_id: Positive
    ) -> dict[str, Any]:
        """Read the selected release's authored version ranges and DLC dependencies from REST v3."""
        async with client_factory() as http:
            nexus = Nexus(http)
            row = await nexus.file(game_domain, mod_id, file_id)
            return await nexus.request(
                "GET", f"/v3/mod-file-versions/{int(row['uid'])}/dependencies"
            )

    @server.tool()
    async def list_files(
        game_domain: str,
        mod_id: Positive,
        category: FileCategory | None = None,
        offset: Offset = 0,
        count: Count = 20,
    ) -> dict[str, Any]:
        """List files including version, category, archive name and size. Use fileId for selection."""
        async with client_factory() as http:
            rows = await Nexus(http).file_list(game_domain, mod_id)
        if category:
            rows = [row for row in rows if row["category"] == category]
        return {
            "totalCount": len(rows),
            "offset": offset,
            "files": rows[offset : offset + count],
        }

    @server.tool()
    async def get_file(
        game_domain: str, mod_id: Positive, file_id: Positive
    ) -> dict[str, Any]:
        """Return the selected file's public metadata and any accessible REST records, including its web page."""
        async with client_factory() as http:
            return await Nexus(http).metadata(game_domain, mod_id, file_id)

    @server.tool()
    async def get_download_links(
        game_domain: str,
        mod_id: Positive,
        file_id: Positive,
        nxm_url: str | None = None,
    ) -> dict[str, Any]:
        """Request signed mirrors for a selected file (or a website authorization step) without saving it."""
        async with client_factory() as http:
            nexus = Nexus(http)
            await nexus.file(game_domain, mod_id, file_id)
            return await nexus.issue_links(game_domain, mod_id, file_id, nxm_url)

    @server.tool()
    async def download_file(
        game_domain: str,
        mod_id: Positive,
        file_id: Positive,
        nxm_url: str | None = None,
    ) -> dict[str, Any]:
        """Save a selected file in NEXUSMODS_DOWNLOAD_DIR. Optionally supply its website-issued nxm:// link."""
        root = Path(
            os.environ.get("NEXUSMODS_DOWNLOAD_DIR")
            or Path.home() / "Downloads" / "NexusMods"
        )
        async with client_factory() as http:
            nexus = Nexus(http)
            metadata = await nexus.metadata(game_domain, mod_id, file_id)
            destination = download_path(root, metadata)
            for attempt in range(2):
                links = await nexus.issue_links(game_domain, mod_id, file_id, nxm_url)
                if "status" in links:
                    return links
                first_mirror = links["data"]["links"][0]["url"]
                try:
                    return await save_archive(
                        http, first_mirror, metadata, destination.parent
                    )
                except NexusError as exc:
                    if attempt or exc.status not in {401, 403, 410}:
                        raise
        raise NexusError("Unable to refresh the download link.")

    return server


def main():
    # Signed URLs contain short-lived credentials. Keep HTTP request URLs out of logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
