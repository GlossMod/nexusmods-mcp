"""Stream a selected archive into a new local file and verify upstream metadata."""

import hashlib
import os
import re
import tempfile
from pathlib import Path, PureWindowsPath
from urllib.parse import urlsplit

import httpx

from .api import NexusError


def archive_name(value: str) -> str:
    if (
        not value
        or value in {".", ".."}
        or re.search(r'[<>:"/\\|?*\x00-\x1f]', value)
        or value != value.rstrip(" .")
        or PureWindowsPath(value).is_reserved()
    ):
        raise ValueError("Nexus supplied an invalid archive filename.")
    return value


def checksums(metadata: dict) -> dict[str, str]:
    expected = {}
    for source in (
        metadata["modFile"],
        metadata.get("v1", {}),
        metadata.get("v3", {}).get("data", {}),
    ):
        for algo in ("sha256", "sha1", "md5"):
            if digest := source.get(algo):
                if (
                    not isinstance(digest, str)
                    or not re.fullmatch(r"[a-fA-F0-9]+", digest)
                    or len(digest) != hashlib.new(algo).digest_size * 2
                ):
                    raise ValueError(f"Invalid upstream {algo} checksum.")
                if algo in expected and expected[algo] != digest.lower():
                    raise ValueError(f"Conflicting upstream {algo} checksums.")
                expected[algo] = digest.lower()
    return expected


def download_path(directory: Path, metadata: dict) -> Path:
    name = archive_name(metadata["modFile"]["uri"])
    destination = directory.expanduser().resolve() / name
    if os.path.lexists(destination):
        raise FileExistsError(f"A file already exists at {destination}.")
    return destination


async def save_archive(
    http: httpx.AsyncClient, url: str, metadata: dict, directory: Path
) -> dict:
    destination = download_path(directory, metadata)
    destination.parent.mkdir(parents=True, exist_ok=True)
    expected = checksums(metadata)
    hashes = {algo: hashlib.new(algo) for algo in {"sha256", *expected}}
    expected_size = metadata["modFile"].get("sizeInBytes")
    if expected_size is None:
        expected_size = metadata.get("v3", {}).get("data", {}).get("size_in_bytes")
    total = 0
    temp_path = None
    try:
        # Follow HTTPS redirects explicitly. This client carries no API credentials.
        for _ in range(8):
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise ValueError("Invalid Nexus mirror URL.")
            async with http.stream(
                "GET",
                url,
                headers={"Accept-Encoding": "identity"},
                follow_redirects=False,
            ) as response:
                if response.is_redirect and "location" in response.headers:
                    url = str(response.url.join(response.headers["location"]))
                    continue
                if response.status_code != 200:
                    raise NexusError(
                        f"Nexus mirror returned HTTP {response.status_code}.",
                        response.status_code,
                    )
                if "text/html" in response.headers.get("Content-Type", "").lower():
                    raise NexusError(
                        "Nexus mirror returned a web page instead of an archive."
                    )
                if (
                    response.headers.get("Content-Encoding", "identity").lower()
                    != "identity"
                ):
                    raise NexusError(
                        "Nexus mirror returned a non-identity content encoding."
                    )
                size_header = response.headers.get("Content-Length")
                if size_header is not None:
                    length = int(size_header)
                    if expected_size is not None and int(expected_size) != length:
                        raise ValueError(
                            "Content-Length does not match Nexus file metadata."
                        )
                    expected_size = length
                with tempfile.NamedTemporaryFile(
                    dir=destination.parent,
                    prefix=".nexus-",
                    suffix=".part",
                    delete=False,
                ) as out:
                    temp_path = Path(out.name)
                    async for chunk in response.aiter_bytes(128 * 1024):
                        total += len(chunk)
                        if expected_size is not None and total > int(expected_size):
                            raise ValueError("Received more bytes than Nexus reported.")
                        out.write(chunk)
                        for digest in hashes.values():
                            digest.update(chunk)
                break
        else:
            raise NexusError("Too many Nexus mirror redirects.")
        if expected_size is not None and total != int(expected_size):
            raise ValueError("Downloaded size does not match Nexus file metadata.")
        actual = {algo: digest.hexdigest() for algo, digest in hashes.items()}
        if any(actual[algo] != wanted for algo, wanted in expected.items()):
            raise ValueError(
                "Downloaded archive checksum does not match Nexus metadata."
            )
        if os.name == "nt":
            os.rename(
                temp_path, destination
            )  # Windows rename refuses existing targets.
        else:
            os.link(
                temp_path, destination
            )  # Atomically publish without replacing an existing file.
        return {
            "path": str(destination),
            "bytes": total,
            "hashes": actual,
            "verifiedUpstreamHashes": expected,
        }
    except httpx.RequestError as exc:
        raise NexusError(f"Download interrupted ({type(exc).__name__}).") from None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
