"""Static checks for static/index.html: structure, JS ids, external URLs, storage, English-only text.

Usage: python3 -I -B notes/app/teste_pagina.py
"""
import html.parser
import os
import re
import sys

PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html")
VOID = {"meta", "img", "input", "br", "link", "hr", "canvas", "source"}


class Parser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack, self.ids, self.errors = [], [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        else:
            self.errors.append(f"</{tag}> without matching open tag")


GLOSSARY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "glossary.md")
# UI words from the Portuguese layout, not all covered by the glossary
EXTRA_PT = ["Câmera", "Áudio", "Vídeo", "Rede", "Sobre", "Ajuda", "Arquivo", "Exibir", "Conectar", "Desconectar",
            "Desconectado", "Conectado", "Ligado", "Desligado", "Senha", "Pronto", "Sessão", "Informações",
            "Controles", "Atualizar", "Silenciar", "Reconectar", "Automático", "Estação", "Relógio", "Bateria"]


def glossary_pt_terms():
    """Portuguese terms from the first column of the glossary's core-terms table."""
    terms = set()
    in_core = False
    for line in open(GLOSSARY, encoding="utf-8"):
        if line.startswith("## "):
            in_core = line.startswith("## Core terms")
        elif in_core and line.startswith("| ") and not line.startswith("| Portuguese") and not line.startswith("|---"):
            cell = re.sub(r"\(.*?\)", "", line.split("|")[1])  # skip English glosses in parentheses
            for word in re.findall(r"[^\W\d_]+", cell):
                if len(word) > 3 and word.lower() not in ("login", "data", "name"):
                    terms.add(word)
    return terms | set(EXTRA_PT)


class VisibleText(html.parser.HTMLParser):
    """Collects what the user reads: text nodes, reader attributes and script string literals."""

    READ_ATTRS = ("title", "aria-label", "alt", "placeholder")

    def __init__(self):
        super().__init__()
        self.in_script = False
        self.chunks = []

    def handle_starttag(self, tag, attrs):
        self.in_script = tag == "script"
        for name, value in attrs:
            if name in self.READ_ATTRS and value:
                self.chunks.append(value)

    def handle_endtag(self, tag):
        self.in_script = False

    def handle_data(self, data):
        if self.in_script:
            # only sentences: paths, ids and MIME types are not text the user reads
            for a, b in re.findall(r'"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'', data):
                literal = a or b
                if " " in literal:
                    self.chunks.append(literal)
        elif data.strip():
            self.chunks.append(data)


def visible_text(src):
    parser = VisibleText()
    parser.feed(src)
    return "\n".join(parser.chunks)


def main():
    src = open(PAGE, encoding="utf-8").read()
    failures = []

    p = Parser()
    p.feed(src)
    p.close()
    if p.stack:
        failures.append(f"unclosed tags: {p.stack}")
    if p.errors:
        failures.append(f"broken nesting: {p.errors}")
    dup = sorted({i for i in p.ids if p.ids.count(i) > 1})
    if dup:
        failures.append(f"duplicate ids: {dup}")

    js = re.search(r"<script>(.*)</script>", src, re.S).group(1)
    used = set(re.findall(r'\$\("([^"]+)"\)', js)) | set(re.findall(r'getElementById\("([^"]+)"\)', js))
    missing = sorted(used - set(p.ids))
    if missing:
        failures.append(f"ids used by JS but absent from HTML: {missing}")

    body = re.sub(r"<!--.*?-->", "", src, flags=re.S)
    external = re.findall(r"(?:https?:)?//[^\s\"')]+", body)
    if external:
        failures.append(f"external URLs: {external}")

    storage = re.findall(r"localStorage|sessionStorage|document\.cookie|indexedDB", js)
    if storage:
        failures.append(f"browser storage used: {storage}")

    # no emoji or pictographs, English-only visible text, no academic wording
    pictographs = [c for c in src if ord(c) >= 0x2600]
    if pictographs:
        failures.append(f"{len(pictographs)} characters >= U+2600 in index.html")
    lowered = src.lower()
    for word in ("acad", "engenharia"):
        if word in lowered:
            failures.append(f"academic wording found: {word!r}")
    visible = visible_text(src)
    leftover = sorted({w for w in glossary_pt_terms() if re.search(r"(?<!\w)%s(?!\w)" % re.escape(w), visible, re.I)})
    if leftover:
        failures.append(f"Portuguese words in visible text: {leftover}")
    print(f"characters >= U+2600: {len(pictographs)}")
    print(f"academic wording: {[w for w in ('acad', 'engenharia') if w in lowered] or 'none'}")
    print(f"Portuguese words in visible text: {leftover or 'none'}")
    print(f"tags balanced: {not p.stack and not p.errors}")
    print(f"ids: {len(p.ids)} (duplicates: {dup or 'none'})")
    print(f"ids used by JS: {len(used)} (missing: {missing or 'none'})")
    print(f"external URLs: {external or 'none'}")
    print(f"browser storage: {storage or 'none'}")
    print("RESULT:", "ok" if not failures else "FAILED: " + "; ".join(failures))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
