"""tests/test_i18n_dictionary.py — 画面の文言は docs/assets/i18n/dict.js（ja / en）の 1 か所だけ。

検査の規則（何を「表示文言の直書き」とみなすか）:
  対象: docs/index.html と docs/assets/**/*.js（dict.js を除く）。
  1. コメントは取り除いてから調べる。JS は簡易トークナイザで文字列・テンプレート・正規表現
     リテラルを読み飛ばしながら // と /* */ を消す（文字列の中の "//" は消さない）。
     HTML は <!-- --> を消し、<style> の中身は CSS として /* */ を消す。
  2. 残ったコード全体に日本語（ひらがな・カタカナ・漢字・全角記号）が 1 文字でもあれば FAIL。
  3. 英語の文: JS の文字列リテラル（'..' / ".." / `..` の地の部分）と HTML のテキストノード・
     表示属性（title / aria-label / placeholder / alt）について、HTML タグと ${...} を除いた上で
     「英字だけの 2 文字以上の語が空白 1 つで 3 語以上続く」箇所があれば FAIL。
     （CSS の値や class 名はハイフン・数字・コロンを含むので語にならない。）
  4. dict.js の ja と en のキー集合が一致しなければ FAIL（片側だけのキーを禁止）。
  5. コードが T("key") / data-i18n="key" で直接参照するキーは辞書に存在しなければ FAIL。
  6. 売買判定の閾値は ind.P["cci_th"] == 100 のまま（±200 は表示用の線のみ。表示の変更で判定を変えていない）。
"""
import json
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
DICT = DOCS / "assets" / "i18n" / "dict.js"

JP = re.compile(r"[　-〿぀-ヿ㐀-䶿一-鿿＀-￯]")
EN3 = re.compile(r"(?<![\w\-.:/#&])[A-Za-z]{2,}(?: [A-Za-z]{2,}){2,}(?![\w\-:(])")
SHOWN_ATTRS = ("title", "aria-label", "placeholder", "alt")


# ── JS tokenizer ─────────────────────────────────────────────────────────────
_REGEX_PREV = set("(,=:[!&|?{};+-*%<>~^")
_REGEX_KW = ("return", "typeof", "case", "in", "of", "delete", "void", "throw", "else")


def js_split(src):
    """→ (code_without_comments, [string literal bodies]). Template literals contribute their
    static parts; ${...} expressions are tokenized recursively as code."""
    out, strings = [], []
    i, n = 0, len(src)

    def prev_sig():
        j = len(out) - 1
        buf = "".join(out[-200:]) if out else ""
        buf = buf.rstrip()
        if not buf:
            return ""
        return buf

    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
            out.append(" ")
            continue
        if c in "'\"":
            j = i + 1
            while j < n and src[j] != c:
                if src[j] == "\\":
                    j += 1
                elif src[j] == "\n":
                    break
                j += 1
            strings.append(src[i + 1:j])
            out.append(src[i:j + 1])
            i = j + 1
            continue
        if c == "`":
            j = i + 1
            static = []
            while j < n and src[j] != "`":
                if src[j] == "\\":
                    static.append(src[j:j + 2])
                    j += 2
                    continue
                if src[j] == "$" and j + 1 < n and src[j + 1] == "{":
                    depth, k = 1, j + 2
                    while k < n and depth:
                        if src[k] == "{":
                            depth += 1
                        elif src[k] == "}":
                            depth -= 1
                        elif src[k] in "'\"`":   # skip nested literal quickly
                            q = src[k]
                            k += 1
                            while k < n and src[k] != q:
                                if src[k] == "\\":
                                    k += 1
                                k += 1
                        k += 1
                    inner_code, inner_str = js_split(src[j + 2:k - 1])
                    strings.extend(inner_str)
                    out.append(" " + inner_code + " ")
                    static.append(" ")
                    j = k
                    continue
                static.append(src[j])
                j += 1
            strings.append("".join(static))
            out.append("``")
            i = j + 1
            continue
        if c == "/":
            p = prev_sig()
            last = p[-1:] if p else ""
            is_re = (not p) or last in _REGEX_PREV or any(p.endswith(k) for k in _REGEX_KW)
            if is_re:
                j, cls = i + 1, False
                while j < n:
                    ch = src[j]
                    if ch == "\\":
                        j += 2
                        continue
                    if ch == "[":
                        cls = True
                    elif ch == "]":
                        cls = False
                    elif ch == "/" and not cls:
                        break
                    elif ch == "\n":
                        break
                    j += 1
                j += 1
                while j < n and src[j].isalpha():
                    j += 1
                out.append("/re/")
                i = j
                continue
        out.append(c)
        i += 1
    return "".join(out), strings


def html_split(src):
    """→ (code_without_comments, [shown texts], [js strings])."""
    src = re.sub(r"<!--.*?-->", " ", src, flags=re.S)
    code_parts, shown, jsstr = [], [], []
    pos = 0
    for m in re.finditer(r"<(script|style)\b[^>]*>(.*?)</\1>", src, flags=re.S | re.I):
        code_parts.append(src[pos:m.start()])
        _html_texts(src[pos:m.start()], shown)
        body = m.group(2)
        if m.group(1).lower() == "script":
            c, s = js_split(body)
            jsstr.extend(s)
            code_parts.append(c)
        else:
            code_parts.append(re.sub(r"/\*.*?\*/", " ", body, flags=re.S))
        pos = m.end()
    code_parts.append(src[pos:])
    _html_texts(src[pos:], shown)
    return "".join(code_parts), shown, jsstr


def _html_texts(markup, shown):
    for m in re.finditer(r">([^<]+)<", markup):
        shown.append(m.group(1))
    for a in SHOWN_ATTRS:
        for m in re.finditer(r'\s%s="([^"]*)"' % a, markup):
            shown.append(m.group(1))


def _strip_markup(s):
    s = re.sub(r"<[^>]*>?", " ", s)
    s = re.sub(r"^[^<]*?>", " ", s) if s.lstrip().startswith(('"', "'")) else s
    s = re.sub(r"&\w+;", " ", s)
    return s


def _targets():
    files = [DOCS / "index.html"] + sorted(p for p in (DOCS / "assets").rglob("*.js") if p != DICT)
    return files


def _scan():
    problems = []
    for f in _targets():
        src = f.read_text(encoding="utf-8")
        rel = f.relative_to(ROOT)
        if f.suffix == ".html":
            code, shown, strings = html_split(src)
        else:
            code, strings = js_split(src)
            shown = []
        for ln, line in enumerate(code.split("\n"), 1):
            if JP.search(line):
                problems.append(f"{rel}: Japanese outside the dictionary: {line.strip()[:120]}")
        for s in strings + shown:
            t = _strip_markup(s)
            m = EN3.search(t)
            if m:
                problems.append(f"{rel}: English sentence outside the dictionary: {m.group(0)!r} in {s.strip()[:100]!r}")
    return problems


def load_dict():
    """dict.js を node で評価して {ja:{...}, en:{...}} を返す。"""
    js = ("global.window={};require(%s);process.stdout.write(JSON.stringify("
          "{d:window.I18N,l:window.I18N_LEGACY||{}}))" % json.dumps(str(DICT)))
    out = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def test_no_display_text_outside_dictionary():
    problems = _scan()
    assert not problems, "display text must live in docs/assets/i18n/dict.js:\n" + "\n".join(problems[:80])


def test_tokenizer_keeps_strings_and_drops_comments():
    code, strings = js_split('const a="x // y"; // 日本語\n/* 英語 too */ const r=/a\\/b/g; const t=`p ${q("in")} s`;')
    assert "日本語" not in code and "英語" not in code
    assert "x // y" in strings and "in" in strings
    assert any(s.startswith("p ") for s in strings)


def test_ja_en_keys_match():
    d = load_dict()["d"]
    ja, en = set(d["ja"]), set(d["en"])
    assert ja == en, f"only ja: {sorted(ja - en)[:40]} / only en: {sorted(en - ja)[:40]}"
    empty = [k for k in ja if not str(d["ja"][k]).strip() or not str(d["en"][k]).strip()]
    assert not empty, f"empty dictionary values: {empty[:40]}"


def test_referenced_keys_exist():
    d = load_dict()["d"]["ja"]
    missing = set()
    for f in _targets():
        src = f.read_text(encoding="utf-8")
        for m in re.finditer(r"""(?<![\w.])T\(\s*["']([A-Za-z0-9_.\-]+)["']\s*([,)+])""", src):
            k = m.group(1)
            if m.group(2) == "+":          # dynamic key: the prefix must name at least one key
                if not any(x.startswith(k) for x in d):
                    missing.add(f"{f.name}: {k}*")
            elif k not in d:
                missing.add(f"{f.name}: {k}")
        for m in re.finditer(r'data-i18n(?:-[a-z]+)?="([^"]+)"', src):
            if m.group(1) not in d:
                missing.add(f"{f.name}: {m.group(1)}")
    assert not missing, f"keys used but not in dict.js: {sorted(missing)}"


def test_cci_trade_threshold_unchanged():
    from marketcalc import ind
    assert ind.P["cci_th"] == 100, "±200 is display-only; the buy/sell threshold stays CCI48 ±100"


# 2026-11: 訳し漏れ対策。辞書の「表示される値」に snake_case（英小文字_英小文字 の形の内部名）を残さない。
# {placeholder} と HTML タグ・属性は除外。画面側の同じ検査は tools/preview_screens.mjs（本番 data.json でも CI で実行）。
_SNAKE = re.compile(r"(?<![A-Za-z0-9_./{-])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![A-Za-z0-9_./}-])")


def test_dictionary_values_have_no_snake_case():
    d = load_dict()["d"]
    bad = []
    for lang in ("ja", "en"):
        for k, v in d[lang].items():
            text = re.sub(r"<[^>]+>", "", re.sub(r"\{\w+\}", "", str(v)))
            hits = sorted(set(_SNAKE.findall(text)))
            if hits:
                bad.append(f"{lang} {k}: {hits}")
    assert not bad, "辞書の値に内部名（snake_case）が残っている:\n" + "\n".join(bad)


# 2026-11: 架空データに出てこない値（本番だけで出る値）も辞書にあることを確かめる。
# 本番 data.json での画面確認（pr_preview の snake_case 検査）で見つかった net_long_context 等の再発防止。
def test_codes_only_seen_in_production_are_translated():
    import sys
    root = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    import fetch_signals as fs
    d = load_dict()["d"]
    need = set()
    for net in (20000, -20000, 0, None):
        state, crowd = fs.classify_imm_positioning(net)
        need.add(f"code.positioning_state.{state}")
    src = (root / "pipeline" / "build_gamma.py").read_text(encoding="utf-8")
    for a in set(re.findall(r'"assumption":\s*"(\w+)"', src)):
        need.add(f"code.gamma_assumption.{a}")
    missing = [f"{lang} {k}" for lang in ("ja", "en") for k in sorted(need) if k not in d[lang]]
    assert not missing, missing
