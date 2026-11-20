"""Convert Zendesk article HTML into clean, self-contained Markdown."""

from __future__ import annotations

import html
import json
import re
import unicodedata
from collections.abc import Mapping
from typing import Any
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Comment, Tag
from markdownify import MarkdownConverter

HEADINGS = ["h1", "h2", "h3", "h4", "h5", "h6"]
ARTICLE_PATH = re.compile(r"^/hc/(?:[a-z]{2}(?:-[a-z]{2})?/)?articles/(\d+)", re.IGNORECASE)
YOUTUBE_EMBED = re.compile(r"youtube(?:-nocookie)?\.com/embed/([\w-]+)")
# Presentation-only wrappers (Zendesk WYSIWYG + pasted Wix markup): keep their text, drop the tag.
UNWRAP_TAGS = ["span", "font", "u", "colgroup", "col", "article"]
DROP_TAGS = ["script", "style", "noscript", "link", "meta", "form", "button", "input", "svg"]
EMPHASIS_TAGS = ["strong", "b", "em", "i"]


def slugify(text: str) -> str:
    """Filesystem-safe ASCII slug: 'Add a YouTube Video!' -> 'add-a-youtube-video'."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def heading_anchor(text: str) -> str:
    """GitHub-flavoured Markdown heading id (before de-duplication)."""
    text = re.sub(r"[^\w\- ]", "", text.strip().lower())
    return text.replace(" ", "-")


def article_to_markdown(
    article: Mapping[str, Any],
    filenames: Mapping[int, str],
    base_url: str,
) -> str:
    """Render one Zendesk article as Markdown with YAML front matter.

    `filenames` maps article id -> local Markdown filename so links between
    articles become relative links inside the scraped corpus.
    """
    soup = BeautifulSoup(article.get("body") or "", "html.parser")
    title = article["title"].strip()

    _drop_noise(soup)
    _embed_media_as_links(soup)
    _rewrite_links(soup, article["html_url"], filenames, base_url)
    _rewrite_in_page_anchors(soup, title)
    _strip_presentation(soup)

    body = _Converter(
        heading_style="ATX",
        bullets="-",
        strong_em_symbol="*",
        newline_style="backslash",  # survives trailing-whitespace stripping, unlike two-space breaks
        table_infer_header=True,
        escape_underscores=False,
        escape_misc=False,
    ).convert_soup(soup)

    front_matter = {
        "id": article["id"],
        "title": title,
        "url": article["html_url"],
        "section_id": article.get("section_id"),
        "labels": article.get("label_names") or [],
        "created_at": article.get("created_at"),
        "updated_at": article.get("updated_at"),
    }
    # JSON scalars/arrays are valid YAML, which keeps quoting correct without a YAML dependency.
    header = "\n".join(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in front_matter.items())
    # The "Article URL:" line is what the assistant is told to cite.
    doc = f"---\n{header}\n---\n\n# {title}\n\nArticle URL: {article['html_url']}\n\n{body}"
    return _tidy(doc)


class _Converter(MarkdownConverter):
    def convert_pre(self, el, text, parent_tags):
        # Zendesk marks unknown languages as `language-auto`; Prism leaves token <span>s inside,
        # and pasted snippets often use <br> instead of literal newlines.
        for br in el.find_all("br"):
            br.replace_with("\n")
        code = el.get_text()
        if not code.strip():
            return ""
        lang = ""
        code_el = el.find("code")
        for cls in (code_el.get("class") if code_el else None) or []:
            if cls.startswith("language-") and cls != "language-auto":
                lang = cls.removeprefix("language-")
        fence = "````" if "```" in code else "```"
        return f"\n\n{fence}{lang}\n{code.strip(chr(10))}\n{fence}\n\n"

    def convert_a(self, el, text, parent_tags):
        if not el.get("href"):
            return text  # bare <a name=...> targets were already resolved to heading anchors
        return super().convert_a(el, text, parent_tags)


def _drop_noise(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(DROP_TAGS):
        tag.decompose()
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()


def _embed_media_as_links(soup: BeautifulSoup) -> None:
    """Markdown cannot embed players; keep the media reachable as a plain link."""
    for frame in soup.find_all("iframe"):
        src = _absolute(frame.get("src", ""))
        match = YOUTUBE_EMBED.search(src)
        if match:
            label, href = "YouTube video", f"https://www.youtube.com/watch?v={match.group(1)}"
        else:
            label, href = frame.get("title") or "Embedded content", src
        _replace_with_link(soup, frame, label, href)
    for video in soup.find_all("video"):
        source = video.get("src") or (video.find("source") or {}).get("src", "")
        _replace_with_link(soup, video, f"Video: {video.get('title') or 'demo'}", _absolute(source))


def _replace_with_link(soup: BeautifulSoup, el: Tag, label: str, href: str) -> None:
    if not href:
        el.decompose()
        return
    link = soup.new_tag("a", href=href)
    link.string = label
    el.replace_with(link)


def _rewrite_links(soup: BeautifulSoup, page_url: str, filenames: Mapping[int, str], base_url: str) -> None:
    help_center_host = urlsplit(base_url).netloc
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:")):
            continue
        parts = urlsplit(href)
        if not parts.scheme and not href.startswith(("/", "//")):
            continue  # malformed author input ("bonus.ly"); leave it untouched
        absolute = urljoin(page_url, href)
        parts = urlsplit(absolute)
        match = ARTICLE_PATH.match(parts.path) if parts.netloc == help_center_host else None
        target = filenames.get(int(match.group(1))) if match else None
        if target:
            a["href"] = f"./{target}" + (f"#{parts.fragment}" if parts.fragment else "")
        else:
            a["href"] = absolute
    for img in soup.find_all("img"):
        if img.get("src"):
            img["src"] = urljoin(page_url, _absolute(img["src"]))
        else:
            img.decompose()


def _rewrite_in_page_anchors(soup: BeautifulSoup, title: str) -> None:
    """Point `#Name` links at the GFM id of the heading the `<a name>`/`id` target sits on.

    Zendesk TOCs link to `<a name="FooBar">` markers that Markdown drops, so
    without this every table-of-contents link in the output would be dead.
    """
    title_el = soup.new_tag("h1")
    title_el.string = title
    soup.insert(0, title_el)  # counted for GFM de-duplication; removed before conversion

    heading_ids: dict[int, str] = {}
    seen: dict[str, int] = {}
    for heading in soup.find_all(HEADINGS):
        base = heading_anchor(heading.get_text(" ", strip=True))
        count = seen.get(base, 0)
        seen[base] = count + 1
        heading_ids[id(heading)] = base if count == 0 else f"{base}-{count}"

    targets: dict[str, str] = {}
    for el in soup.find_all(lambda t: t.get("name") or t.get("id")):
        heading = el if el.name in HEADINGS else el.find_next(HEADINGS)
        if heading is None:
            continue
        for key in (el.get("name"), el.get("id")):
            if key:
                targets.setdefault(key.lower(), heading_ids[id(heading)])
    for anchor in heading_ids.values():
        targets.setdefault(anchor, anchor)  # links already written as GFM ids

    for a in soup.find_all("a", href=re.compile(r"^#.")):
        # Authors mix case (`#limitations` -> name="Limitations") and double-escape (`&amp;amp;`).
        fragment = html.unescape(a["href"][1:]).lower()
        anchor = targets.get(fragment)
        if anchor:
            a["href"] = f"#{anchor}"
    title_el.decompose()


def _strip_presentation(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(UNWRAP_TAGS):
        tag.unwrap()
    # Bold/italic inside headings only adds `**` noise to the heading text.
    for heading in soup.find_all(HEADINGS):
        for tag in heading.find_all(EMPHASIS_TAGS):
            tag.unwrap()
    # Emphasis around nothing but whitespace or an image renders as stray `**`.
    for tag in soup.find_all(EMPHASIS_TAGS):
        if not tag.get_text(strip=True):
            tag.unwrap()
    for a in soup.find_all("a", href=False):
        if not a.get_text(strip=True) and not a.find("img"):
            a.decompose()
    _callout_tables_to_blockquotes(soup)


def _callout_tables_to_blockquotes(soup: BeautifulSoup) -> None:
    """Zendesk authors use one-column tables as NOTE/TIP boxes; a blockquote reads (and chunks) better."""
    for table in soup.find_all("table"):
        rows = table.select(":scope > tr, :scope > thead > tr, :scope > tbody > tr")
        cells = [row.find_all(["td", "th"], recursive=False) for row in rows]
        if not rows or any(len(row_cells) != 1 for row_cells in cells):
            continue
        quote = soup.new_tag("blockquote")
        for (cell,) in cells:
            cell.name = "div"
            quote.append(cell.extract())
        table.replace_with(quote)


def _absolute(url: str) -> str:
    return f"https:{url}" if url.startswith("//") else url


def _tidy(markdown: str) -> str:
    markdown = markdown.replace("\u00a0", " ").replace("\u200b", "")
    lines = [line.rstrip() for line in markdown.splitlines()]
    markdown = "\n".join(lines)
    markdown = re.sub(r"^(#{1,6}|-|\d+\.)$\n?", "", markdown, flags=re.MULTILINE)  # empty headings/bullets
    markdown = re.sub(r"^[ \t]*\\$\n?", "", markdown, flags=re.MULTILINE)  # repeated <br><br>
    # A <br> right before a block (blank line, list item, heading) renders as a literal backslash.
    markdown = re.sub(r"\\$(?=\n\s*(?:$|[-*+] |\d+\. |#|>))", "", markdown, flags=re.MULTILINE)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    return markdown.strip() + "\n"
