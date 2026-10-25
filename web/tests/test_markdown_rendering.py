"""Browser contracts for Markdown upgrades, using the real parser and sanitizer."""

import json

import pytest
from playwright.sync_api import Page, expect

from .conftest import SSE_CHAT_MOCK, chat_history, route_chat_history, sse_delta, stored_answer

pytestmark = pytest.mark.browser

SOURCES = [
    {
        "index": index,
        "document": f"Guideline {index}.pdf",
        "page": index,
        "category": "Regulatory",
        "score": 0.9,
        "snippet": f"Evidence passage {index}.",
    }
    for index in (1, 2)
]


def _render_answer(page: Page, mode: str, text: str, lang: str = "en"):
    """Exercise stream completion, stored-history hydration, or blocking chat."""
    payload = {
        "response": text,
        "sources": SOURCES,
        "cited": [1, 2],
        "retrieved": 2,
        "suggested_questions": [],
    }
    if mode == "history":
        route_chat_history(
            page, chat_history(stored_answer("Requirements?", text, sources=SOURCES))
        )
    elif mode == "stream":
        body = SSE_CHAT_MOCK.partition("event: delta")[0]
        body += "".join(sse_delta(text[i : i + 7]) for i in range(0, len(text), 7))
        body += f"event: final\ndata: {json.dumps(payload)}\n\n"
        body += 'event: suggestions\ndata: {"suggested_questions":[]}\n\n'
        body += f'event: done\ndata: {{"finish_reason":"stop","chars":{len(text)}}}\n\n'
        page.context.route(
            "**/api/chat/stream",
            lambda route: route.fulfill(status=200, content_type="text/event-stream", body=body),
        )
    else:
        assert mode == "blocking"
        page.context.route(
            "**/api/chat",
            lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps(payload)
            ),
        )

    path = "/c/c0ffee00-0000-4000-8000-000000000001" if mode == "history" else "/"
    page.goto(f"{path}?testing=true&lang={lang}")
    expect(page.locator("#authenticated-view")).to_be_visible()
    if mode != "history":
        if mode == "blocking":
            page.evaluate(
                """async () => {
                  const { CONFIG } = await import('/static/js/modules/config.js');
                  CONFIG.STREAMING = false;
                }"""
            )
        page.locator("#query-input").fill("Requirements?")
        page.locator("#send-button").click()

    message = page.locator(".chatbot-message").last
    expect(message.locator(".source-trigger")).to_be_visible()
    return message.locator(".message-content")


@pytest.mark.parametrize("mode", ["stream", "history", "blocking"])
@pytest.mark.parametrize("lang", ["en", "ar"])
@pytest.mark.parametrize("width", [390, 1600])
def test_markdown_layout_and_citations(browser_page: Page, mode: str, lang: str, width: int):
    """Formatting and clickable evidence survive all three rendering paths."""
    page = browser_page
    page.set_viewport_size({"width": width, "height": 900})
    heading = "متطلبات التسجيل" if lang == "ar" else "Registration requirements"
    claim = "يجب تقديم **الطلب**" if lang == "ar" else "Submit the **application**"
    text = (
        f"## {heading}\n\n{claim} [1][2].\n\n"
        "- Certificate [1]\n- Form\n\n"
        "| Item | Source |\n| --- | --- |\n| Form | [2] |\n\n"
        "Use `data[1]`.\n\n```python\nrows = data[2]\n```\n\n"
        "[Guidance](https://example.com/guide)\n\n"
        "> Keep a copy."
    )
    content = _render_answer(page, mode, text, lang)

    expect(page.locator("html")).to_have_attribute("dir", "rtl" if lang == "ar" else "ltr")
    expect(content).to_have_attribute("dir", "auto")
    expect(content.locator("h2")).to_have_text(heading)
    expect(content.locator("strong")).to_have_count(1)
    expect(content.locator("ul.message-list > li")).to_have_count(2)
    expect(content.locator("table tbody tr")).to_have_count(1)
    expect(content.locator("pre.message-code-block code.language-python")).to_contain_text(
        "rows = data[2]"
    )
    expect(content.locator("code.message-inline-code")).to_have_text("data[1]")
    expect(content.locator("blockquote")).to_contain_text("Keep a copy.")
    expect(content.locator('a[href="https://example.com/guide"]')).to_have_text("Guidance")
    expect(content.locator(".cite-marker")).to_have_count(4)
    expect(content.locator("pre .cite-marker, code .cite-marker, a .cite-marker")).to_have_count(0)
    for selector in ("h2", "table", "pre"):
        box = content.locator(selector).bounding_box()
        assert box and box["width"] > 0 and box["height"] > 0
        assert box["x"] >= -1 and box["x"] + box["width"] <= width + 1

    content.locator('.cite-marker[data-cite="2"]').first.click()
    expect(page.locator("#source-panel")).to_be_visible()
    expect(page.locator("#source-panel")).to_contain_text("Evidence passage 2.")


@pytest.mark.parametrize("mode", ["stream", "history", "blocking"])
def test_markdown_is_sanitized_before_inserting_into_the_browser(browser_page: Page, mode: str):
    """Neither raw HTML nor unsafe Markdown links may survive DOMPurify."""
    page = browser_page
    page.add_init_script("window.__markdownXss = 0;")
    text = (
        "<script>window.__markdownXss = 1</script>\n\n"
        '<img src="/missing-markdown-test-image" onerror="window.__markdownXss = 2">\n\n'
        '<svg onload="window.__markdownXss = 3"><text>unsafe</text></svg>\n\n'
        '<iframe srcdoc="<script>parent.__markdownXss = 4</script>"></iframe>\n\n'
        "[unsafe](javascript:window.__markdownXss=5)\n\n"
        "[encoded](java&#x73;cript:window.__markdownXss=6)\n\n"
        "[data](data:text/html;base64,PHNjcmlwdD4=)\n\n"
        "Safe **answer** [1]."
    )
    content = _render_answer(page, mode, text)

    expect(content.locator("strong")).to_have_text("answer")
    expect(content.locator(".cite-marker")).to_have_count(1)
    expect(content.locator("script, svg, iframe, object, embed")).to_have_count(0)
    expect(content.locator("[onerror], [onload], [onclick], [srcdoc]")).to_have_count(0)
    expect(content.locator('a[href^="javascript:"], a[href^="data:"]')).to_have_count(0)
    page.wait_for_function(
        """() => [...document.querySelectorAll('.message-content img')]
          .every(image => image.complete)"""
    )
    assert page.evaluate("window.__markdownXss") == 0


def test_each_incremental_render_is_sanitized_and_finish_matches_full_parse(browser_page: Page):
    """Use the actual DOM/sanitizer while incomplete fences and tables arrive."""
    page = browser_page
    page.goto("/?testing=true")
    expect(page.locator("#authenticated-view")).to_be_visible()
    result = page.evaluate(
        """async () => {
          const { MarkdownStream } = await import('/static/js/modules/stream-render.js');
          const root = document.createElement('div');
          document.querySelector('#messages').append(root);
          const text = '## متطلبات التسجيل\\n\\nSubmit [1][2].\\n\\n'
            + '| Item | Source |\\n| --- | --- |\\n| Form | [1] |\\n\\n'
            + '```python\\nrows = data[2]\\n```\\n\\n'
            + '<img src="/missing-markdown-test-image" onerror="window.__markdownXss=1">'
            + '\\n\\n[unsafe](javascript:alert(1))';
          window.__markdownXss = 0;
          const stream = new MarkdownStream(root);
          let frames = 0;
          for (let i = 0; i < text.length; i += 7) {
            stream.push(text.slice(i, i + 7));
            await new Promise(requestAnimationFrame);
            frames++;
            if (root.querySelector('script, [onerror], [onload], a[href^="javascript:"]')) {
              throw new Error('Unsafe intermediate render');
            }
          }
          const finished = stream.finish();
          const comparison = document.createElement('div');
          const oneShot = new MarkdownStream(comparison);
          oneShot.finish(text);
          const matches = root.innerHTML === comparison.innerHTML;
          const shape = {
            tables: root.querySelectorAll('table').length,
            code: root.querySelector('pre code')?.textContent.trim(),
            pending: root.querySelectorAll('.md-pending').length,
          };
          const canonical = 'Canonical **answer** [1].';
          stream.finish(canonical);
          const canonicalApplied = stream.buffer === canonical
            && root.querySelector('strong')?.textContent === 'answer';
          stream.finish('');
          const emptyApplied = stream.buffer === '' && root.textContent === '';
          root.remove();
          return { matches, frames, finished: finished === text, shape,
            canonicalApplied, emptyApplied, executed: window.__markdownXss };
        }"""
    )
    assert result["matches"] and result["finished"]
    assert result["frames"] > 20
    assert result["shape"] == {"tables": 1, "code": "rows = data[2]", "pending": 0}
    assert result["canonicalApplied"] and result["emptyApplied"]
    assert result["executed"] == 0
