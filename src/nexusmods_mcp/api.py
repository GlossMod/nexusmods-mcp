"""Queries against Nexus-owned API endpoints. API keys never go to download mirrors."""

import os
import re
import time
from urllib.parse import parse_qs, urlsplit

import httpx

from . import queries

API = "https://api.nexusmods.com"


class NexusError(ValueError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def domain_name(value: str) -> str:
    domain = value.lower().strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,99}", domain):
        raise ValueError("Use a Nexus game domain such as skyrimspecialedition.")
    return domain


def web_url(domain: str, mod_id: int, file_id: int | None = None) -> str:
    page = f"https://www.nexusmods.com/{domain_name(domain)}/mods/{mod_id}"
    return page if file_id is None else f"{page}?tab=files&file_id={file_id}"


def nxm_parameters(link: str | None, domain: str, mod_id: int, file_id: int) -> dict:
    if not link:
        return {}
    parsed = urlsplit(link)
    if (
        parsed.scheme.lower() != "nxm"
        or parsed.netloc.lower() != domain
        or parsed.path != f"/mods/{mod_id}/files/{file_id}"
        or parsed.fragment
    ):
        raise ValueError("NXM link must identify the selected game, mod and file.")
    values = parse_qs(parsed.query, keep_blank_values=True)
    if "key" not in values and "expires" not in values:
        return {}
    if any(len(values.get(k, [])) != 1 or not values[k][0] for k in ("key", "expires")):
        raise ValueError("NXM link needs a single key and expires pair.")
    if not re.fullmatch(r"\d{1,12}", values["expires"][0]):
        raise ValueError("Invalid NXM expiry timestamp.")
    expires = int(values["expires"][0])
    if expires <= time.time():
        raise NexusError(
            "NXM link has expired. Generate a fresh link on the file page.", 410
        )
    return {"key": values["key"][0], "expires": expires}


class Nexus:
    def __init__(self, http: httpx.AsyncClient):
        self.http = http
        self.headers = {
            "User-Agent": "nexusmods-mcp/0.1.0",
            "Application-Name": "nexusmods-mcp",
        }
        for variable, header, prefix in (
            ("NEXUSMODS_API_KEY", "apikey", ""),
            ("NEXUSMODS_ACCESS_TOKEN", "Authorization", "Bearer "),
        ):
            credential = os.environ.get(variable, "").strip()
            if credential:
                if not re.fullmatch(r"[!-~]+", credential):
                    raise NexusError(f"{variable} contains invalid header characters.")
                self.headers[header] = prefix + credential

    async def request(self, method: str, path: str, **kwargs):
        try:
            response = await self.http.request(
                method, API + path, headers=self.headers, **kwargs
            )
        except httpx.RequestError as exc:
            raise NexusError(
                f"Nexus API connection failed ({type(exc).__name__})."
            ) from None
        if not response.is_success:
            retry = response.headers.get("Retry-After")
            message = f"Nexus {path} returned HTTP {response.status_code}."
            if retry:
                message += f" Retry after {retry}."
            raise NexusError(message, response.status_code)
        try:
            return response.json()
        except ValueError:
            raise NexusError(f"Nexus {path} returned invalid JSON.") from None

    async def gql(self, query: str, variables: dict) -> dict:
        payload = await self.request(
            "POST", "/v2/graphql", json={"query": query, "variables": variables}
        )
        if errors := payload.get("errors"):
            raise NexusError(
                "Nexus GraphQL: " + ", ".join(e["message"] for e in errors)
            )
        if not isinstance(payload.get("data"), dict):
            raise NexusError("Nexus GraphQL returned no data.")
        return payload["data"]

    async def ids(self, domain: str, mod_id: int) -> dict:
        result = await self.gql(queries.GAME_ID, {"domain": domain_name(domain)})
        game = result["game"]
        if not game:
            raise NexusError("Unknown Nexus game domain.", 404)
        return {"gid": str(game["id"]), "mid": str(mod_id)}

    async def rest_mod(self, domain: str, mod_id: int) -> dict:
        return await self.request(
            "GET", f"/v3/games/{domain_name(domain)}/mods/{mod_id}"
        )

    async def file_list(self, domain: str, mod_id: int) -> list:
        data = await self.gql(queries.FILES, await self.ids(domain, mod_id))
        return data["modFiles"]

    async def file(self, domain: str, mod_id: int, file_id: int) -> dict:
        for row in await self.file_list(domain, mod_id):
            if row["fileId"] == file_id:
                return row
        raise NexusError("File does not belong to this mod or is unavailable.", 404)

    async def metadata(self, domain: str, mod_id: int, file_id: int) -> dict:
        domain = domain_name(domain)
        record = await self.file(domain, mod_id, file_id)
        result = {"modFile": record, "filePage": web_url(domain, mod_id, file_id)}
        lookups = [("v3", f"/v3/mod-file-versions/{int(record['uid'])}")]
        if "apikey" in self.headers:
            lookups.append(
                ("v1", f"/v1/games/{domain}/mods/{mod_id}/files/{file_id}.json")
            )
        for label, path in lookups:
            try:
                result[label] = await self.request("GET", path)
            except NexusError as exc:
                result.setdefault("unavailable", {})[label] = str(exc)
        return result

    async def issue_links(
        self, domain: str, mod_id: int, file_id: int, nxm_url: str | None
    ) -> dict:
        domain = domain_name(domain)
        file_page = web_url(domain, mod_id, file_id)
        try:
            params = nxm_parameters(nxm_url, domain, mod_id, file_id)
            path = f"/v3/games/{domain}/mod-file-versions/{file_id}/download-link"
            data = await self.request("GET", path, params=params)
        except NexusError as exc:
            if exc.status not in {400, 401, 403, 410}:
                raise
            return {
                "status": "web_authorization_required",
                "filePage": file_page,
                "httpStatus": exc.status,
                "reason": str(exc),
            }
        if not data.get("data", {}).get("links"):
            raise NexusError("Nexus returned no available download mirrors.")
        return data
