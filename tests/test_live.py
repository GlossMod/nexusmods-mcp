"""Opt-in real-site check. Run with NEXUSMODS_LIVE_TEST=1; downloads go to a temp directory."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@unittest.skipUnless(
    os.getenv("NEXUSMODS_LIVE_TEST") == "1", "opt-in real Nexus service"
)
class LiveNexus(unittest.IsolatedAsyncioTestCase):
    async def test_skyui(self):
        with tempfile.TemporaryDirectory() as root:
            env = {**os.environ, "NEXUSMODS_DOWNLOAD_DIR": root}
            # Launch the installed module using this environment's interpreter.
            params = StdioServerParameters(
                command=sys.executable, args=["-m", "nexusmods_mcp.server"], env=env
            )
            async with (
                stdio_client(params) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                tools = await session.list_tools()
                self.assertIn("download_file", {tool.name for tool in tools.tools})

                async def call(tool, **args):
                    result = await session.call_tool(tool, args)
                    self.assertFalse(result.isError, result.content)
                    return result.structuredContent or json.loads(
                        result.content[0].text
                    )

                games = await call("find_games", name="Skyrim", count=20)
                domain = next(
                    row["domainName"]
                    for row in games["nodes"]
                    if row["domainName"] == "skyrimspecialedition"
                )
                page = await call(
                    "find_mods",
                    game_domain=domain,
                    name="SkyUI",
                    sort="endorsements",
                    count=10,
                )
                match = next(row for row in page["nodes"] if row["modId"] == 12604)
                ids = {"game_domain": domain, "mod_id": match["modId"]}
                info = await call("get_mod", **ids)
                self.assertEqual(info["mod"]["name"], "SkyUI")
                self.assertIn("gallery_images", info["v3"]["data"])
                req = (await call("get_requirements", **ids, count=1))[
                    "modRequirements"
                ]
                self.assertIn("dlcRequirements", req)
                files = await call("list_files", **ids, category="MAIN")
                selected = dict(ids, file_id=files["files"][0]["fileId"])
                metadata = await call("get_file", **selected)
                self.assertEqual(metadata["modFile"]["fileId"], selected["file_id"])
                result = await call("download_file", **selected)
                summary = {
                    "tools": len(tools.tools),
                    "url": info["websiteUrl"],
                    "images": len(info["v3"]["data"]["gallery_images"]),
                    "required": req["nexusRequirements"]["totalCount"],
                    "reverse": req["modsRequiringThisMod"]["totalCount"],
                    "main_files": files["totalCount"],
                    "file_id": selected["file_id"],
                }
                if "path" in result:
                    self.assertEqual(
                        Path(result["path"]).stat().st_size,
                        int(metadata["modFile"]["sizeInBytes"]),
                    )
                    summary.update(
                        download="saved",
                        bytes=result["bytes"],
                        sha256=result["hashes"]["sha256"],
                    )
                else:
                    self.assertEqual(result["status"], "web_authorization_required")
                    self.assertEqual(list(Path(root).iterdir()), [])
                    summary.update(
                        download="requires website / account authorization",
                        http=result["httpStatus"],
                    )
                print(summary)
