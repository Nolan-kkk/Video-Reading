"""Validate the exact public video URLs the worker is allowed to access."""

import re
from typing import Literal
from urllib.parse import urljoin, urlsplit

import httpx

from videomind.errors import SourceError

Platform = Literal["bilibili", "douyin"]
_DOUYIN_PATH = re.compile(r"/video/([0-9]{1,25})/?")
_DOUYIN_SHARE = re.compile(r"/share/video/([0-9]{1,25})/?")
_SHORT_PATH = re.compile(r"/([A-Za-z0-9_-]{3,64})/?")
_SHORT_HOSTS = {"b23.tv": "bilibili", "v.douyin.com": "douyin"}


def normalize_source_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        if parsed.hostname in _SHORT_HOSTS:
            match = _SHORT_PATH.fullmatch(parsed.path)
            if (
                parsed.scheme not in {"http", "https"}
                or parsed.username is not None
                or parsed.password is not None
                or parsed.port not in {None, 443}
                or match is None
            ):
                raise ValueError
            return f"https://{parsed.hostname}/{match[1]}"
        if parsed.hostname in {"bilibili.com", "www.bilibili.com", "m.bilibili.com"}:
            # Kept separate so existing Bilibili callers retain their narrow contract.
            from videomind.extractors.bilibili import normalize_url

            return normalize_url(value)
        match = _DOUYIN_PATH.fullmatch(parsed.path)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"douyin.com", "www.douyin.com"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
            or match is None
        ):
            raise ValueError
        return f"https://www.douyin.com/video/{match[1]}"
    except ValueError:
        raise SourceError(
            "仅支持 B站/抖音视频或官方分享短链；不接受其他平台或带账号的 URL。"
        ) from None


def source_platform(canonical: str) -> Platform:
    if normalize_source_url(canonical) != canonical:
        raise SourceError("视频地址不是规范化地址。")
    return (
        "douyin"
        if urlsplit(canonical).hostname in {"www.douyin.com", "v.douyin.com"}
        else "bilibili"
    )


def is_short_url(canonical: str) -> bool:
    return urlsplit(canonical).hostname in _SHORT_HOSTS


def resolve_source_url(value: str, *, transport: httpx.BaseTransport | None = None) -> str:
    """Resolve only fixed official short hosts; never follow an unchecked redirect."""
    current = normalize_source_url(value)
    if not is_short_url(current):
        return current
    platform = source_platform(current)
    try:
        with httpx.Client(
            timeout=10, follow_redirects=False, trust_env=False, transport=transport
        ) as client:
            for _ in range(3):
                # stream prevents downloading a response body from an unexpected 200 page.
                with client.stream("GET", current) as response:
                    if response.status_code not in {301, 302, 303, 307, 308}:
                        raise ValueError("No redirect")
                    location = response.headers.get("location")
                    if not location or len(location) > 8192:
                        raise ValueError("Invalid redirect")
                target = urljoin(current, location)
                parsed = urlsplit(target)
                if (
                    parsed.scheme != "https"
                    or parsed.username is not None
                    or parsed.password is not None
                    or parsed.port not in {None, 443}
                ):
                    raise ValueError("Invalid destination")
                # Douyin's documented share redirect may expose the ID on iesdouyin.
                if platform == "douyin" and parsed.hostname in {
                    "iesdouyin.com",
                    "www.iesdouyin.com",
                }:
                    match = _DOUYIN_SHARE.fullmatch(parsed.path)
                    if not match:
                        raise ValueError("Invalid share path")
                    target = f"https://www.douyin.com/video/{match[1]}"
                target = normalize_source_url(target)
                if source_platform(target) != platform:
                    raise ValueError("Cross-platform redirect")
                if not is_short_url(target):
                    return target
                if urlsplit(target).hostname != urlsplit(current).hostname:
                    raise ValueError("Unexpected short host")
                current = target
    except (httpx.HTTPError, ValueError, SourceError):
        raise SourceError("无法安全解析平台分享短链；请提供标准视频链接或本地文件。") from None
    raise SourceError("分享短链重定向次数超限；请提供标准视频链接。")
