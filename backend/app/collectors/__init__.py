"""Collecting reviews from product links.

Each website has its own adapter (one file each). An adapter:
  1. recognises the website's links      (hosts)
  2. reads the product ID from a link     (parse)
  3. fetches the product and its reviews  (collect) — only through an
     official or otherwise permitted source.

Websites whose terms don't allow automated access (Amazon, Flipkart) have an
adapter too, but it only explains why their reviews can't be collected.

No adapter ever downloads the user's URL itself: the URL is only parsed, and
requests go to fixed, known API addresses. This also means a malicious link
can't make the server fetch arbitrary internal addresses (SSRF).
"""
