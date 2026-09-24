#!/usr/bin/env python3
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / 'app' / 'static' / 'index.html'
CSS_DIR = ROOT / 'app' / 'static' / 'assets' / 'css'
JS_DIR = ROOT / 'app' / 'static' / 'assets' / 'js'

STYLE_NAMES = ['base.css', 'reports.css', 'print.css']
SCRIPT_NAMES = ['app-core.js', 'app-workers.js']


def main() -> int:
    text = HTML.read_text(encoding='utf-8')
    CSS_DIR.mkdir(parents=True, exist_ok=True)
    JS_DIR.mkdir(parents=True, exist_ok=True)

    style_matches = list(re.finditer(r'<style[^>]*>(.*?)</style>', text, re.I | re.S))
    script_matches = [
        m for m in re.finditer(r'<script([^>]*)>(.*?)</script>', text, re.I | re.S)
        if 'src=' not in m.group(1).lower()
    ]

    if not style_matches and not script_matches:
        print('No inline assets found. Nothing to extract.')
        return 0

    replacements = []
    for i, m in enumerate(style_matches):
        name = STYLE_NAMES[i] if i < len(STYLE_NAMES) else f'style-{i+1}.css'
        (CSS_DIR / name).write_text(m.group(1).strip() + '\n', encoding='utf-8')
        replacements.append((m.span(), f'<link rel="stylesheet" href="/static/assets/css/{name}">'))

    for i, m in enumerate(script_matches):
        name = SCRIPT_NAMES[i] if i < len(SCRIPT_NAMES) else f'script-{i+1}.js'
        (JS_DIR / name).write_text(m.group(2).strip() + '\n', encoding='utf-8')
        replacements.append((m.span(), f'<script src="/static/assets/js/{name}"></script>'))

    for span, repl in sorted(replacements, key=lambda x: x[0][0], reverse=True):
        text = text[:span[0]] + repl + text[span[1]:]

    HTML.write_text(text, encoding='utf-8')
    print('Frontend assets extracted successfully.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
