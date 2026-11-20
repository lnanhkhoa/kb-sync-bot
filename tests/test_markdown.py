from optibot.markdown import article_to_markdown
from optibot.scrape import assign_filenames

BASE = "https://support.optisigns.com"


def render(body: str, filenames: dict[int, str] | None = None) -> str:
    article = {
        "id": 1,
        "title": "Add a YouTube Video",
        "html_url": f"{BASE}/hc/en-us/articles/1-Add-a-YouTube-Video",
        "body": body,
    }
    return article_to_markdown(article, filenames or {}, BASE)


def test_front_matter_and_citation_line():
    md = render("<p>Hi</p>")
    assert md.startswith('---\nid: 1\ntitle: "Add a YouTube Video"\n')
    assert "\n# Add a YouTube Video\n\nArticle URL: https://support.optisigns.com/hc/en-us/articles/1-Add-a-YouTube-Video\n" in md


def test_toc_links_resolve_to_heading_ids():
    md = render(
        '<ul><li><a href="#StepOne">Step one</a></li><li><a href="#q&amp;amp;a">Q&amp;A</a></li></ul>'
        '<p><a name="StepOne"></a></p><h2 id="h_01X"><strong>Step 1: Upload</strong></h2>'
        '<p><a name="Q&amp;A"></a></p><h2>Q &amp; A</h2>'
    )
    assert "[Step one](#step-1-upload)" in md
    assert "[Q&A](#q--a)" in md
    assert "## Step 1: Upload" in md  # no ** noise inside headings


def test_article_links_become_relative_and_others_absolute():
    md = render(
        f'<a href="{BASE}/hc/en-us/articles/42-Pair-a-Screen#Step2">pair</a> '
        '<a href="/hc/en-us/articles/99-Not-Scraped">other</a> '
        '<img src="/hc/article_attachments/7" alt="shot">',
        filenames={42: "pair-a-screen.md"},
    )
    assert "[pair](./pair-a-screen.md#Step2)" in md
    assert f"[other]({BASE}/hc/en-us/articles/99-Not-Scraped)" in md
    assert f"![shot]({BASE}/hc/article_attachments/7)" in md


def test_code_block_keeps_line_breaks_and_language():
    md = render('<pre><code class="language-auto">a --flag<br>b <span class="token">c</span></code></pre>'
                '<pre><code class="language-json">{"k": 1}</code></pre>')
    assert "```\na --flag\nb c\n```" in md
    assert '```json\n{"k": 1}\n```' in md


def test_media_embeds_become_links_and_noise_is_dropped():
    md = render(
        '<script>track()</script><style>p{}</style>'
        '<p><iframe src="//www.youtube-nocookie.com/embed/abc_12"></iframe></p>'
        '<video title="Demo" src="https://cdn.example/v.mp4"></video>'
    )
    assert "[YouTube video](https://www.youtube.com/watch?v=abc_12)" in md
    assert "[Video: Demo](https://cdn.example/v.mp4)" in md
    assert "track()" not in md and "<" not in md.split("---", 2)[2]


def test_single_column_table_becomes_blockquote():
    md = render('<table><tbody><tr><td><strong>NOTE:</strong> Pro plan only.</td></tr></tbody></table>'
                "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>")
    assert "> **NOTE:** Pro plan only." in md
    assert "| A | B |\n| --- | --- |\n| 1 | 2 |" in md


def test_filenames_are_slugs_with_id_on_collision():
    names = assign_filenames([
        {"id": 1, "title": "Pairing: Android!"},
        {"id": 2, "title": "FAQ"},
        {"id": 3, "title": "faq"},
    ])
    assert names == {1: "pairing-android.md", 2: "faq-2.md", 3: "faq-3.md"}
