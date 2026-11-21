"""Exercise the actual stdio boundary with known Nexus responses and precise failure cases."""

import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from nexusmods_mcp.api import NexusError, nxm_parameters
from nexusmods_mcp.download import archive_name, save_archive

BODY = b"archive"
HASH = hashlib.sha256(BODY).hexdigest()
FILE = {
    "uid": "99",
    "fileId": 8,
    "modId": 7,
    "category": "MAIN",
    "uri": "test.zip",
    "sizeInBytes": str(len(BODY)),
    "version": "2.1",
    "name": "Test",
}
MOD = {"modId": 7, "name": "Test Mod", "game": {"domainName": "testgame"}}


def start_fixture():
    from nexusmods_mcp.server import build_server

    calls = 0

    def handle(request):
        nonlocal calls
        path = request.url.path
        if request.url.host == "mirror.example":
            assert (
                "apikey" not in request.headers
                and "authorization" not in request.headers
            )
            if path == "/stale":
                return httpx.Response(403)
            return httpx.Response(200, content=BODY)
        assert (
            request.url.host == "api.nexusmods.com"
            and request.headers["apikey"] == "fixture"
        )
        if path == "/v2/graphql":
            body = json.loads(request.content)
            q, v = body["query"], body["variables"]
            if "query GameId(" in q:
                data = {"game": {"id": 1, "domainName": v["domain"]}}
            elif "query Games(" in q:
                assert v["filter"]["name"] == [{"value": "test", "op": "WILDCARD"}]
                data = {
                    "games": {
                        "totalCount": 2,
                        "nodesCount": 1,
                        "nodes": [{"domainName": "testgame"}],
                    }
                }
            elif "query Mods(" in q:
                assert (
                    v["filter"]["gameDomainName"][0]["value"] == "testgame"
                    and v["offset"] == 1
                )
                data = {"mods": {"totalCount": 2, "nodesCount": 1, "nodes": [MOD]}}
            elif "query ModDetails(" in q:
                data = {"mod": MOD}
            elif "query Files(" in q:
                data = {"modFiles": [FILE]}
            elif "query Requirements(" in q:
                assert (v["offset"], v["reverseOffset"]) == (1, 3)
                data = {
                    "mod": {
                        "modRequirements": {
                            "nexusRequirements": {
                                "nodes": [
                                    {"modName": "Framework", "notes": "Install first"}
                                ]
                            },
                            "modsRequiringThisMod": {"nodes": [{"modName": "Addon"}]},
                            "dlcRequirements": [],
                        }
                    }
                }
            else:
                raise AssertionError(q)
            return httpx.Response(200, json={"data": data})
        if path.endswith("/mods/7"):
            return httpx.Response(
                200, json={"data": {"gallery_images": [], "future_field": 42}}
            )
        if path.endswith("download-link"):
            calls += 1
            endpoint = "stale" if calls == 1 else "usable"
            return httpx.Response(
                200,
                json={
                    "data": {"links": [{"url": f"https://mirror.example/{endpoint}"}]}
                },
            )
        if path.endswith("/dependencies"):
            return httpx.Response(403)
        if path.endswith("/99"):
            return httpx.Response(200, json={"data": {"size_in_bytes": 7}})
        if path.endswith("/8.json"):
            return httpx.Response(200, json={"sha256": HASH, "file_id": 8})
        raise AssertionError(path)

    build_server(lambda: httpx.AsyncClient(transport=httpx.MockTransport(handle))).run()


class StdioWorkflow(unittest.IsolatedAsyncioTestCase):
    async def test_search_details_requirements_file_and_download(self):
        with tempfile.TemporaryDirectory() as root:
            env = {
                **os.environ,
                "NEXUSMODS_DOWNLOAD_DIR": root,
                "NEXUSMODS_API_KEY": "fixture",
            }
            fixture_script = str(Path(__file__).resolve())
            params = StdioServerParameters(
                command=sys.executable,
                args=[fixture_script, "--fixture-server"],
                env=env,
            )
            async with stdio_client(params) as (r, w), ClientSession(r, w) as session:
                await session.initialize()
                self.assertEqual(len((await session.list_tools()).tools), 9)

                async def call(name, args):
                    reply = await session.call_tool(name, args)
                    self.assertFalse(reply.isError, reply.content)
                    return reply.structuredContent or json.loads(reply.content[0].text)

                games = await call("find_games", {"name": "test", "count": 1})
                domain = games["nodes"][0]["domainName"]
                mods = await call(
                    "find_mods", {"game_domain": domain, "offset": 1, "count": 1}
                )
                ids = {"game_domain": domain, "mod_id": mods["nodes"][0]["modId"]}
                details = await call("get_mod", ids)
                self.assertEqual(
                    details["websiteUrl"], "https://www.nexusmods.com/testgame/mods/7"
                )
                self.assertEqual(details["v3"]["data"]["future_field"], 42)
                req = (
                    await call(
                        "get_requirements", dict(ids, offset=1, reverse_offset=3)
                    )
                )["modRequirements"]
                self.assertEqual(
                    req["modsRequiringThisMod"]["nodes"][0]["modName"], "Addon"
                )
                self.assertEqual(
                    req["nexusRequirements"]["nodes"][0]["notes"], "Install first"
                )
                files = await call("list_files", dict(ids, category="MAIN"))
                selected = dict(ids, file_id=files["files"][0]["fileId"])
                self.assertEqual(
                    (await call("get_file", selected))["v1"]["sha256"], HASH
                )
                self.assertTrue(
                    (await session.call_tool("get_file_requirements", selected)).isError
                )
                expired = await call(
                    "get_download_links",
                    dict(
                        selected,
                        nxm_url="nxm://testgame/mods/7/files/8?key=k&expires=1",
                    ),
                )
                self.assertEqual(expired["httpStatus"], 410)
                self.assertIn("file_id=8", expired["filePage"])
                saved = await call("download_file", selected)
                self.assertEqual(Path(saved["path"]).read_bytes(), BODY)
                self.assertEqual(saved["verifiedUpstreamHashes"], {"sha256": HASH})
                self.assertTrue(
                    (await session.call_tool("download_file", selected)).isError
                )
                self.assertTrue(
                    (
                        await session.call_tool("get_file", dict(ids, file_id=100))
                    ).isError
                )
                self.assertEqual([p.name for p in Path(root).iterdir()], ["test.zip"])


class DownloaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_interruption_or_integrity_error_removes_partial(self):
        class Broken(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b"partial"
                raise httpx.ReadError("sample interruption")

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for response, metadata in [
                (httpx.Response(200, stream=Broken()), {"modFile": FILE}),
                (httpx.Response(200, content=b"wrong size"), {"modFile": FILE}),
                (
                    httpx.Response(200, content=BODY),
                    {"modFile": FILE, "v1": {"sha256": "a" * 64}},
                ),
            ]:
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(lambda _, reply=response: reply)
                ) as http:
                    with self.assertRaises(ValueError):
                        await save_archive(
                            http, "https://mirror.example/download", metadata, root
                        )
                self.assertEqual(list(root.iterdir()), [])

    def test_nxm_pair_and_paths(self):
        expiry = int(time.time()) + 1200
        good = f"nxm://testgame/mods/7/files/8?key=abc&expires={expiry}&user_id=42"
        self.assertEqual(
            nxm_parameters(good, "testgame", 7, 8), {"key": "abc", "expires": expiry}
        )
        for link in (
            good.replace("/7/", "/9/"),
            good.replace("testgame", "other"),
            good + "&key=dup",
            good.replace("expires=", "other="),
        ):
            with self.assertRaises(ValueError):
                nxm_parameters(link, "testgame", 7, 8)
        for name in ("../file", "bad/file", "C:alternate", "CON.zip", ".."):
            with self.assertRaises(ValueError):
                archive_name(name)

    async def test_graphql_error_and_permission_denied(self):
        from nexusmods_mcp.api import Nexus

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, json={"data": {}, "errors": [{"message": "unavailable"}]}
                )
            )
        ) as http:
            with self.assertRaisesRegex(NexusError, "unavailable"):
                await Nexus(http).gql("query {}", {})
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(401))
        ) as http:
            info = await Nexus(http).issue_links("testgame", 7, 8, None)
            self.assertEqual(info["httpStatus"], 401)
            self.assertEqual(info["status"], "web_authorization_required")


if __name__ == "__main__":
    if "--fixture-server" in sys.argv:
        start_fixture()
    else:
        unittest.main()
