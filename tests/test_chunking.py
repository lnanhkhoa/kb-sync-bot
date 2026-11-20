from pathlib import Path

from optibot.chunking import GEMINI_MAX_WORDS, MIN_WORDS, Article, chunk_article, load_article

URL = "https://support.optisigns.com/hc/en-us/articles/1-Add-YouTube"


def make(body: str) -> Article:
    return Article(1, "Add YouTube", URL, "add-youtube", body, "h")


def words(n: int, tag: str = "w") -> str:
    return " ".join(f"{tag}{i}" for i in range(n))


def test_every_chunk_is_citable_and_carries_its_section():
    body = f"Intro {words(MIN_WORDS)}\n\n## Setup\n\n{words(MIN_WORDS - 10)}\n\n### Android\n\nTap pair."
    chunks = chunk_article(make(body))
    assert len(chunks) == 2
    for chunk in chunks:
        assert chunk.startswith(f"# Add YouTube\nArticle URL: {URL}\n")
    assert "Section: Setup > Android" not in chunks[0]
    assert "Section: Setup\n\n## Setup" in chunks[1]
    assert chunks[1].rstrip().endswith("### Android\n\nTap pair.")  # small subsection merged


def test_oversized_code_block_is_split_into_valid_fenced_pieces():
    code = "\n".join(f"line{i} {words(9)}" for i in range(120))  # 1200 words
    chunks = chunk_article(make(f"## Script\n\n```bash\n{code}\n```"))
    assert len(chunks) >= 3
    for chunk in chunks:
        assert len(chunk.split()) <= GEMINI_MAX_WORDS
        assert chunk.count("```") == 2 and "```bash\n" in chunk


def test_long_paragraph_and_long_heading_path_stay_under_gemini_limit():
    heading = words(200, "h")
    chunks = chunk_article(make(f"## {heading}\n\n{words(2000)}"))
    assert all(len(c.split()) <= GEMINI_MAX_WORDS for c in chunks)
    assert " ".join(c.split("\n\n", 1)[1] for c in chunks).split()[-1] == "w1999"


def test_relative_article_links_point_to_live_urls():
    chunks = chunk_article(
        make("See [pairing](./pair-a-screen.md#step-2) and [x](./unknown.md)."),
        {"pair-a-screen.md": "https://support.optisigns.com/hc/en-us/articles/2-Pair"},
    )
    assert "[pairing](https://support.optisigns.com/hc/en-us/articles/2-Pair#step-2)" in chunks[0]
    assert "[x](./unknown.md)" in chunks[0]


def test_load_article_strips_preamble_and_hash_tracks_content(tmp_path: Path):
    path = tmp_path / "add-youtube.md"
    doc = f'---\nid: 1\ntitle: "Add YouTube"\nurl: "{URL}"\n---\n\n# Add YouTube\n\nArticle URL: {URL}\n\nBody ---\n'
    path.write_text(doc)
    first = load_article(path)
    assert (first.id, first.slug, first.body) == (1, "add-youtube", "Body ---")
    path.write_text(doc.replace("Body", "Changed"))
    assert load_article(path).content_hash != first.content_hash
