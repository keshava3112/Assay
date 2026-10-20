from datetime import datetime

from assay.text import (contains_verbatim, context_around, dates_in, html_to_text, months_between, norm,
                        registrable_domain, same_site, sentences, top_passages)


def test_html_to_text_drops_chrome_and_collects_links():
    html = """<html><head><title>Kosha Credit</title><script>var x=1</script></head><body>
      <nav>Home About Careers</nav><h1>Credit for makers</h1>
      <p>We offer <a href="/loans">working-capital loans</a> to small manufacturers.</p>
      <footer>© 2026 Kosha</footer></body></html>"""
    title, text, links = html_to_text(html, "https://kosha.example/")
    assert title == "Kosha Credit"
    assert "working-capital loans to small manufacturers" in text
    assert "var x" not in text and "Careers" not in text and "©" not in text
    assert "https://kosha.example/loans" in links


def test_verbatim_is_tolerant_of_typography_not_of_words():
    page = "Kosha Credit is headquartered in Bengaluru and has disbursed over ₹900 crore."
    assert contains_verbatim(page, "kosha credit is HEADQUARTERED   in Bengaluru")
    assert contains_verbatim("He said “we lend to makers” today", 'He said "we lend to makers" today')
    assert not contains_verbatim(page, "Kosha Credit is headquartered in Mumbai")
    assert not contains_verbatim(page, "Bengaluru")  # too short to prove anything
    assert norm("A  B") == "a b"


def test_sentences_and_context():
    text = "First one here. Second sentence is longer! Third? Yes."
    assert sentences(text)[:2] == ["First one here.", "Second sentence is longer!"]
    ctx = context_around("x" * 400 + " the quote lives here " + "y" * 400, "the quote lives here", width=20)
    assert "the quote lives here" in ctx and len(ctx) < 120


def test_dates_and_months():
    found = dates_in("raised in March 2025, announced 14 Sept 2026 and again on 2026-10-02")
    assert datetime(2025, 3, 1) in found
    assert any(d.year == 2026 and d.month == 9 for d in found)
    assert any(d.year == 2026 and d.month == 10 for d in found)
    assert months_between(datetime(2025, 3, 1), datetime(2026, 10, 19)) == 19
    assert dates_in("no dates at all here") == []


def test_registrable_domain_handles_multi_part_suffixes():
    assert registrable_domain("https://www.kosha.example/about") == "kosha.example"
    assert registrable_domain("https://blog.razorpay.co.in/x") == "razorpay.co.in"
    assert registrable_domain("https://news.bbc.co.uk") == "bbc.co.uk"
    assert same_site("https://a.kosha.example", "http://kosha.example/press")
    assert not same_site("https://kosha.example", "https://kosha-credit.example")


def test_bm25_prefers_relevant_windows():
    docs = [("a", "The office has a nice cafe. We like plants."),
            ("b", "Kosha raised a Series A of $12M in July 2026. The round was led by Banyan.")]
    top = top_passages(docs, "Series A funding round raised", k=1)
    assert top[0][0] == "b"
    assert "Series A" in top[0][1]
