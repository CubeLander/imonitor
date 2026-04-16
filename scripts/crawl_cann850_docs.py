#!/usr/bin/env python3
"""Crawl CANN 8.5 docs from hiascend and convert pages to markdown.

Example:
  python3 scripts/crawl_cann850_docs.py \
    --max-pages 3000 \
    --out-dir develop/cann850_docs
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as html_to_md

START_URL = "https://www.hiascend.com/document/detail/zh/canncommercial/850/index/index.html"
DOMAIN = "www.hiascend.com"
PATH_PREFIX = "/document/detail/zh/canncommercial/850/"
USER_AGENT = "imonitor-cann850-crawler/0.1"


@dataclass
class PageResult:
    url: str
    title: str
    markdown_path: str
    html_path: str | None


def normalize_url(url: str) -> str:
    base, _frag = urldefrag(url)
    parsed = urlparse(base)
    # Canonicalize by dropping query/params; doc pages are identified by path.
    return parsed._replace(params="", query="", fragment="").geturl()


def is_target_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    if parsed.netloc != DOMAIN:
        return False
    if not parsed.path.startswith(PATH_PREFIX):
        return False
    return parsed.path.endswith(".html")


def iter_links(soup: BeautifulSoup, current_url: str) -> Iterable[str]:
    for node in soup.find_all("a", href=True):
        href = node["href"].strip()
        if not href:
            continue
        absolute = normalize_url(urljoin(current_url, href))
        if is_target_url(absolute):
            yield absolute


def pick_content_node(soup: BeautifulSoup):
    selectors = [
        "div#topic-content",
        "div.topic-content",
        "div.doc-content",
        "div.document-content",
        "section.document-content",
        "div.single-doc-index",
        "article",
        "main",
        "div.document-detail-content",
    ]
    for selector in selectors:
        node = soup.select_one(selector)
        if node is not None:
            return node
    return soup.body or soup


def build_output_relpath(url: str) -> Path:
    parsed = urlparse(url)
    rel = parsed.path[len(PATH_PREFIX) :]
    rel = rel.strip("/")
    if not rel:
        rel = "index/index.html"
    path = Path(rel)
    if path.suffix.lower() == ".html":
        path = path.with_suffix(".md")
    else:
        path = path / "index.md"
    return path


def fetch_page(session: requests.Session, url: str, timeout: float) -> str | None:
    try:
        resp = session.get(url, timeout=timeout)
        if resp.status_code != 200:
            print(f"[warn] {resp.status_code} {url}")
            return None
        resp.encoding = resp.encoding or "utf-8"
        return resp.text
    except requests.RequestException as exc:
        print(f"[warn] request failed {url}: {exc}")
        return None


def convert_html_to_markdown(raw_html: str, source_url: str) -> tuple[str, str]:
    soup = BeautifulSoup(raw_html, "lxml")
    title = soup.title.get_text(strip=True) if soup.title else source_url
    content = pick_content_node(soup)

    for tag in content.find_all(
        ["script", "style", "noscript", "svg", "header", "footer", "nav", "aside", "form"]
    ):
        tag.decompose()

    noisy_selector = "[class*='footer'], [id*='footer'], [class*='header'], [id*='header'], [class*='breadcrumb'], [class*='toc']"
    for tag in content.select(noisy_selector):
        tag.decompose()

    for node in content.find_all(string=True):
        txt = node.strip()
        if txt in {"返回顶部"}:
            node.extract()

    md_body = html_to_md(str(content), heading_style="ATX", strip=["img"])
    lines: list[str] = []
    for line in md_body.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append(line)
            continue
        if "版权所有" in stripped:
            continue
        if stripped in {"返回顶部"}:
            continue
        if re.search(r"(法律声明|隐私政策|Cookie协议|用户协议|联系我们)", stripped):
            continue
        lines.append(line)
    md_body = "\n".join(lines)
    md_body = re.sub(r"\n{3,}", "\n\n", md_body).strip()

    header = [
        f"# {title}",
        "",
        f"- Source: {source_url}",
        "",
    ]
    return "\n".join(header) + md_body + "\n", title


def crawl(args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir).resolve()
    md_dir = out_dir / "markdown"
    html_dir = out_dir / "html"
    out_dir.mkdir(parents=True, exist_ok=True)
    md_dir.mkdir(parents=True, exist_ok=True)
    if args.save_html:
        html_dir.mkdir(parents=True, exist_ok=True)

    queue = deque([normalize_url(args.start_url)])
    seen: set[str] = set()
    results: list[PageResult] = []

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    while queue and len(results) < args.max_pages:
        url = queue.popleft()
        if url in seen:
            continue
        seen.add(url)

        html = fetch_page(session, url, timeout=args.timeout)
        if html is None:
            continue

        soup = BeautifulSoup(html, "lxml")
        for link in iter_links(soup, url):
            if link not in seen:
                queue.append(link)

        md_rel = build_output_relpath(url)
        md_path = md_dir / md_rel
        md_path.parent.mkdir(parents=True, exist_ok=True)

        markdown, title = convert_html_to_markdown(html, url)
        md_path.write_text(markdown, encoding="utf-8")

        html_saved: str | None = None
        if args.save_html:
            html_rel = md_rel.with_suffix(".html")
            html_path = html_dir / html_rel
            html_path.parent.mkdir(parents=True, exist_ok=True)
            html_path.write_text(html, encoding="utf-8")
            html_saved = str(html_path.relative_to(out_dir))

        results.append(
            PageResult(
                url=url,
                title=title,
                markdown_path=str(md_path.relative_to(out_dir)),
                html_path=html_saved,
            )
        )

        print(f"[ok] ({len(results)}/{args.max_pages}) {url}")
        if args.sleep > 0:
            time.sleep(args.sleep)

    manifest = {
        "start_url": args.start_url,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "page_count": len(results),
        "max_pages": args.max_pages,
        "save_html": args.save_html,
        "items": [r.__dict__ for r in results],
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    index_lines = [
        "# CANN 8.5 文档抓取索引",
        "",
        f"- Start URL: {args.start_url}",
        f"- Pages: {len(results)}",
        f"- Generated at: {manifest['generated_at']}",
        "",
    ]
    for item in results:
        index_lines.append(f"- [{item.title}]({item.markdown_path})")

    (out_dir / "INDEX.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    print(f"[done] wrote {len(results)} pages to {out_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl CANN 8.5 docs to markdown")
    parser.add_argument("--start-url", default=START_URL)
    parser.add_argument("--out-dir", default="develop/cann850_docs")
    parser.add_argument("--max-pages", type=int, default=500)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--sleep", type=float, default=0.1)
    parser.add_argument("--save-html", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    crawl(args)


if __name__ == "__main__":
    main()
