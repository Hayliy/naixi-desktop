"""HTML 解析工具 —— 标准库 html.parser 实现，零正则、零第三方依赖。

替代 tools.py / api.py 中脆弱的正则 HTML 抓取与清洗（正则解析 HTML 是经典暴雷点：
页面结构微变即失效，且多行/嵌套/属性顺序变化都会让正则漏匹配）。

所有函数输入为 HTML 字符串，输出为纯文本或 (url, text) 列表。
"""
from html.parser import HTMLParser


class _TextExtractor(HTMLParser):
    """提取标签间纯文本，忽略 <script>/<style> 内部内容（与原正则先去 script/style 行为一致）。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._parts = []
        self._skip = 0  # 处于 script/style 内的深度

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1

    def handle_data(self, data):
        if self._skip == 0:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip > 0:
            self._skip -= 1

    def get_text(self):
        # 文本节点之间补一个空格：还原旧正则"每个标签边界插一个空格"的间距，
        # 同时避免不同标签内的词被粘连（如 <li>a</li><li>b</li> → "a b" 而非 "ab"）。
        return " ".join(self._parts)


def strip_tags(html: str) -> str:
    """去除所有标签，返回折叠空白后的纯文本（忽略 script/style）。"""
    if not html:
        return ""
    p = _TextExtractor()
    p.feed(html)
    return " ".join(p.get_text().split())


class _LinkExtractor(HTMLParser):
    """收集所有 <a href>text</a> 链接（忽略 script/style 内）。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self._in_a = False
        self._href = ""
        self._cur = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._in_a = True
            self._href = dict(attrs).get("href", "")
            self._cur = []

    def handle_data(self, data):
        if self._in_a:
            self._cur.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._in_a:
            text = "".join(self._cur).strip()
            if self._href:
                self.links.append((self._href, text))
            self._in_a = False


def extract_links(html: str):
    """返回 [(url, text), ...]，包含所有 <a> 链接。"""
    if not html:
        return []
    p = _LinkExtractor()
    p.feed(html)
    return p.links


class _ImgExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.images = []

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            d = dict(attrs)
            src = d.get("src", "")
            if src:
                self.images.append((src, d.get("alt", "")))


def extract_images(html: str):
    """返回 [(src, alt), ...]，包含所有 <img>。"""
    if not html:
        return []
    p = _ImgExtractor()
    p.feed(html)
    return p.images


def extract_title(html: str) -> str:
    """取 <title>...</title> 文本（大小写不敏感，跨多行）。无则返回空串。"""
    if not html:
        return ""
    low = html.lower()
    start = low.find("<title>")
    if start == -1:
        # <title ...> 带属性的情况
        start = low.find("<title ")
        if start == -1:
            return ""
        gt = html.find(">", start)
        if gt == -1:
            return ""
        start = gt + 1
    else:
        start = start + len("<title>")
    end = low.find("</title>", start)
    if end == -1:
        return ""
    return " ".join(html[start:end].split())


class _BingResults(HTMLParser):
    """提取 Bing 搜索结果标题链接。

    覆盖两种结构：
      主格式：<li class="b_algo"><h2><a href>title</a></h2>...</li>
      回退格式：<a href><h2>title</h2></a>
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self._h2 = False
        self._h2_in_a = False
        self._a_open = False
        self._a_href = ""
        self._a_text = []

    def handle_starttag(self, tag, attrs):
        if tag == "h2":
            if self._a_open:
                self._h2_in_a = True
            else:
                self._h2 = True
        elif tag == "a":
            self._a_open = True
            self._a_href = dict(attrs).get("href", "")
            self._a_text = []
            self._h2_in_a = False

    def handle_data(self, data):
        if self._a_open:
            self._a_text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._a_open:
            text = "".join(self._a_text).strip()
            if self._a_href and (self._h2 or self._h2_in_a):
                self.results.append((self._a_href, text))
            self._a_open = False
            self._a_href = None
            self._h2_in_a = False
        elif tag == "h2":
            self._h2 = False


def extract_bing_results(html: str):
    """返回 [(url, title), ...]，最多取前若干由调用方截断。"""
    if not html:
        return []
    p = _BingResults()
    p.feed(html)
    return p.results


class _SnippetExtractor(HTMLParser):
    """提取 class 含 'b_lineclamp' 的 <p> 文本（Bing 摘要片段）。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.snippets = []
        self._in = False
        self._cur = []

    def handle_starttag(self, tag, attrs):
        if tag == "p":
            cls = dict(attrs).get("class", "")
            if "b_lineclamp" in cls:
                self._in = True
                self._cur = []

    def handle_data(self, data):
        if self._in:
            self._cur.append(data)

    def handle_endtag(self, tag):
        if tag == "p" and self._in:
            text = "".join(self._cur).strip()
            if text:
                self.snippets.append(text)
            self._in = False


def extract_snippets(html: str):
    """返回 [text, ...]，Bing 摘要片段列表。"""
    if not html:
        return []
    p = _SnippetExtractor()
    p.feed(html)
    return p.snippets
