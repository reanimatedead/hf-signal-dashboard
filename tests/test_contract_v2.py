"""tests/test_contract_v2.py — Task 5 契約テスト（v2 検証層）。

指示書 §5-1。既存 258 件は消さず、これを追加する。目的は「動いているつもり」を
機械的に潰すこと。人間の記憶に頼る検査を作らない。各アサーションは失敗時に
「何が壊れたか」が分かるメッセージを持つ。

検査対象は CI で generation 後に生成される docs/*.json（.gitignore 済・生成物）。
ローカルでも直近の pipeline 実行で実体が存在する前提。ファイル欠落は「生成が
壊れた」＝ fail-closed とみなし、skip せず fail させる（それが検証層の役目）。
"""
import json
import pathlib
import re

import pytest

DOCS = pathlib.Path(__file__).resolve().parents[1] / "docs"

EQUITY_TABS = ("nikkei225", "dow30", "nasdaq100", "sp500")
# ティッカーでない識別子。これらの link は finance.yahoo.com/quote/ を指してはならない
# （Yahoo に存在しない銘柄コードで 404 / 誤誘導になるため）。
NON_TICKER_MARKERS = (
    "_IMM", "BUFFETT", "JP2Y", "JP10Y", "JP30Y", "EU2Y", "EU10Y", "EU30Y",
)
# 結合タブが束ねるソースリスト（getCombinedRows の入力）。行の link 保持が要件。
COMBINED_SOURCES = ("rates", "volatility", "imm", "crypto", "valuation")
REGIME_ALLOWED = {
    "growth_shock_dominant", "inflation_policy_shock_dominant", "transition",
}

# ── 銘柄件数の劣化検知（2026-07-30）──────────────────────────────────────
# min_count は「期待値の90%」でなく "現在の構成銘柄数" を初期基準にする（いま全部を
# FAIL させても意味がないため）。target は full index membership。乖離率をテスト出力に必ず表示。
# カウントは構成銘柄のみ（各 equity タブに1本ずつ pin される ^index proxy は除外）。
EQUITY_MIN_COUNTS = {"nikkei225": 140, "dow30": 30, "nasdaq100": 90, "sp500": 100}
EQUITY_TARGET_COUNTS = {"nikkei225": 225, "dow30": 30, "nasdaq100": 100, "sp500": 500}
# dow30 の構成銘柄数の上限は 30。31 は指数本体(^DJI)か入替前銘柄の混入を示す。
DOW30_MAX_CONSTITUENTS = 30


def _constituent_count(rows):
    """構成銘柄数（^index proxy 行を除く）。"""
    return sum(1 for r in rows if isinstance(r, dict)
               and not str(r.get("symbol", "")).startswith("^"))


def _load(name):
    p = DOCS / name
    assert p.exists(), (
        f"{p} が存在しない。CI では generation 後に生成される想定。ローカルでは "
        f"pipeline を実行してから pytest を回すこと。欠落＝生成が壊れている疑い。"
    )
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        pytest.fail(f"{p} が JSON として読めない: {e}")


def _read_index():
    p = DOCS / "index.html"
    assert p.exists(), f"{p} が存在しない"
    return p.read_text(encoding="utf-8")


def _iter_market_rows(data):
    """(category, row) を全 markets リストについて列挙。"""
    for cat, rows in (data.get("markets") or {}).items():
        if isinstance(rows, list):
            for r in rows:
                if isinstance(r, dict):
                    yield cat, r


# ─────────────────────────── リンク ───────────────────────────
def test_every_market_row_has_link_and_kind():
    data = _load("data.json")
    bad = []
    total = 0
    for cat, r in _iter_market_rows(data):
        total += 1
        sym = r.get("symbol", "?")
        L = r.get("link")
        if not isinstance(L, dict):
            bad.append(f"{cat}/{sym}: link 欠落")
        elif "kind" not in L:
            bad.append(f"{cat}/{sym}: link.kind 欠落")
    assert total > 0, "markets に行が 1 件もない（データが空）"
    assert not bad, f"link / link.kind を欠く行 {len(bad)} 件: {bad[:10]}"


def test_non_ticker_links_do_not_point_to_yahoo_quote():
    data = _load("data.json")
    bad = []
    for cat, r in _iter_market_rows(data):
        sym = r.get("symbol", "")
        if not any(mk in sym for mk in NON_TICKER_MARKERS):
            continue
        url = ((r.get("link") or {}).get("url")) or ""
        if "finance.yahoo.com/quote/" in url:
            bad.append(f"{cat}/{sym} -> {url}")
    assert not bad, (
        "非ティッカー識別子が Yahoo の quote ページを指している（404/誤誘導）: "
        f"{bad}"
    )


def test_vix_and_move_link_kind_is_quote():
    data = _load("data.json")
    vol = {r.get("symbol"): r for _, r in _iter_market_rows(data) if _ == "volatility"}
    for sym in ("VIX", "MOVE"):
        assert sym in vol, f"volatility に {sym} が無い"
        kind = (vol[sym].get("link") or {}).get("kind")
        assert kind == "quote", f"{sym} の link.kind は 'quote' であるべき（実際: {kind!r}）"


def test_combined_tab_sources_retain_link():
    """結合タブ(rates_vol / pos_val)の各行が link を保持しているか。

    getCombinedRows の .map() で link が落ちて実バグになった箇所。
    JS は Python から直接叩けないため、(a) 結合タブが束ねる 5 ソースの全行が
    link を持つこと（データ側保証）と (b) index.html の getCombinedRows が
    link を写像していること（回帰ガード）の両面で守る。
    """
    data = _load("data.json")
    markets = data.get("markets") or {}
    bad = []
    for src in COMBINED_SOURCES:
        for r in markets.get(src, []):
            if isinstance(r, dict) and not isinstance(r.get("link"), dict):
                bad.append(f"{src}/{r.get('symbol','?')}")
    assert not bad, f"結合タブ元ソースで link を欠く行: {bad[:10]}"

    html = _read_index()
    m = re.search(r"function getCombinedRows\(\)\{.*?\n\}", html, re.DOTALL)
    assert m, "index.html に getCombinedRows 関数が見つからない"
    body = m.group(0)
    n = body.count("link: r.link")
    assert n >= len(COMBINED_SOURCES), (
        "getCombinedRows が link を写像している行が足りない（link 脱落バグの再発）: "
        f"'link: r.link' を {n} 箇所しか検出できず、期待 >= {len(COMBINED_SOURCES)}"
    )


# ─────────────────────────── 被覆 ───────────────────────────
# NOTE: 被覆率（量）の判定は health_gate の 90% に一本化した（Task 5 で 95%/90% と
# 二重指定したのは設計ミス）。契約テストは「質」= 不変条件のみを見る。ready 率の数値
# 閾値はここでは検査しない。DATA_CONTRACT §14「被覆率閾値の一本化」参照。


def test_unavailable_equity_rows_have_chart_error():
    """equity タブの unavailable 行は理由(chart_error)を必ず持つ（質の検査）。

    equity の unavailable は「取得を試みて失敗/劣化した」状態なので、なぜ落ちたかを
    必ず記録する（no-data / degraded / 例外 を後から区別できるように）。
    ※ 非 equity（imm/valuation 等）の unavailable は「その市場に per-symbol チャート系列
      が構造的に無い」設計状態であり chart_error を持たない。ゆえに equity 限定で検査する。
    """
    data = _load("data.json")
    markets = data.get("markets") or {}
    bad = []
    for tab in EQUITY_TABS:
        for r in markets.get(tab, []):
            if r.get("chart_status") == "unavailable" and not r.get("chart_error"):
                bad.append(f"{tab}/{r.get('symbol','?')}")
    assert not bad, (
        f"equity の unavailable 行が chart_error を欠く 計 {len(bad)} 件: {bad[:20]}"
    )


def test_chart_status_is_valid_enum():
    data = _load("data.json")
    markets = data.get("markets") or {}
    allowed = {"ready", "pending", "unavailable"}
    bad = []
    for tab in EQUITY_TABS:
        for r in markets.get(tab, []):
            cs = r.get("chart_status")
            if cs not in allowed:
                bad.append(f"{tab}/{r.get('symbol','?')}: {cs!r}")
    assert not bad, f"chart_status が ready/pending/unavailable 以外: {bad[:10]}"


def test_ready_rows_have_real_ohlc_in_chart_file():
    """ready の行は charts/{tab}.json に実体があり ohlc が空でない。

    フラグ(chart_status=ready)だけ見て中身を見なかったのが過去の見落とし原因。
    """
    data = _load("data.json")
    markets = data.get("markets") or {}
    bad = []
    for tab in EQUITY_TABS:
        chart = _load(f"charts/{tab}.json")
        for r in markets.get(tab, []):
            if r.get("chart_status") != "ready":
                continue
            sym = r.get("symbol")
            c = chart.get(sym)
            if not c:
                bad.append(f"{tab}/{sym}: chart 実体なし")
                continue
            d1 = c.get("1d") or {}
            if not d1.get("available"):
                bad.append(f"{tab}/{sym}: 1d.available=False")
            if not (d1.get("ohlc") or []):
                bad.append(f"{tab}/{sym}: 1d.ohlc が空")
    assert not bad, f"ready なのに中身が無い行: {bad[:10]}"


def test_bollinger_bands_upper_gt_basis_gt_lower():
    """BB の中身の妥当性を検査する（フラグでなく実体）。

    正当な None と不正な None を区別する:
      - state == "insufficient_data" → 帯が None なのは**正当**（真に本数不足の短命銘柄）。
        順序検査はスキップする。build は 288 本未満で必ずこの state を出す。
      - それ以外（"neutral"/"..._touch"）で帯が None → **不正**。
        これは NaN 劣化フレーム（行はあるが Close が NaN）が _json_safe で null 化され、
        ready のまま空帯で配信された兆候。今回 CI を止めた事象そのもの。捕捉し続ける。
      - 帯が数値なら upper > basis > lower が成立すること。

    影響範囲を必ず全件数で報告する（過去に bad[:10] 打ち切りで総数が分からず判断を誤った）。
    """
    violations = []           # 不正な None or 順序不正（総数を報告）
    legit_insufficient = 0    # 正当な insufficient_data（参考カウント）
    for tab in EQUITY_TABS:
        chart = _load(f"charts/{tab}.json")
        for sym, c in chart.items():
            bb = ((c.get("1d") or {}).get("indicators") or {}).get("bollinger_bands") or {}
            for period, pv in bb.items():
                if not isinstance(pv, dict):
                    continue
                for sd, sv in pv.items():
                    if not isinstance(sv, dict):
                        continue
                    state = sv.get("state")
                    u, b, l = sv.get("upper"), sv.get("basis"), sv.get("lower")
                    if None in (u, b, l):
                        if state == "insufficient_data":
                            legit_insufficient += 1          # 正当（本数不足）
                        else:
                            violations.append(
                                f"{tab}/{sym} {period}/{sd}: state={state!r} なのに帯が None "
                                f"{(u, b, l)}（NaN 劣化の疑い）")
                    elif not (u > b > l):
                        violations.append(
                            f"{tab}/{sym} {period}/{sd}: upper>basis>lower 不成立 {(u, b, l)}")
    assert not violations, (
        f"BB 帯の不正 計 {len(violations)} 件"
        f"（正当な insufficient_data は別途 {legit_insufficient} 件・許容）: "
        f"先頭20件={violations[:20]}"
    )


def test_ready_symbols_have_valid_bb48():
    """ready(＝chart 実体を持つ)銘柄は最低でも BB48 が有効であること。

    ready は 48 本以上の有効 Close を意味する（build ガード）。したがって 48 期間 BB は
    必ず計算できるはず。48 が insufficient_data / None なら ready の付与が誤り
    （＝ready↔有効BB の結線が壊れている）。288 は本数不足なら insufficient_data 可。
    """
    bad = []
    for tab in EQUITY_TABS:
        chart = _load(f"charts/{tab}.json")
        for sym, c in chart.items():
            if (c.get("1d") or {}).get("available") is not True:
                continue
            b48 = (((c.get("1d") or {}).get("indicators") or {})
                   .get("bollinger_bands") or {}).get("48") or {}
            for sd in ("std_2", "std_3"):
                sv = b48.get(sd) or {}
                if sv.get("basis") is None:
                    bad.append(f"{tab}/{sym} 48/{sd}: state={sv.get('state')!r} basis=None")
    assert not bad, f"ready なのに BB48 が無効な銘柄 計 {len(bad)} 件: {bad[:20]}"


# ─────────────────────────── 地域 ───────────────────────────
def test_rates_regions_are_us_jp_eu():
    data = _load("data.json")
    regions = sorted({
        r.get("region") for _, r in _iter_market_rows(data) if _ == "rates"
    })
    assert set(regions) == {"US", "JP", "EU"}, (
        f"markets.rates の region は {{US, JP, EU}} の 3 種であるべき（実際: {regions}）"
    )


def test_correlations_labels_and_align():
    data = _load("data.json")
    c = data.get("correlations") or {}
    labels = c.get("labels")
    assert isinstance(labels, list) and len(labels) == 12, (
        f"correlations.labels は 12 件であるべき（実際: {len(labels) if isinstance(labels, list) else labels}）"
    )
    assert c.get("align") == "inner_join", (
        f"correlations.align は 'inner_join' であるべき（実際: {c.get('align')!r}）"
    )


# ─────────────────────────── 恒等式（macro_v2）───────────────────────────
def test_macro_v2_fisher_identity():
    mac = _load("macro_v2.json")
    fisher = (mac.get("identities") or {}).get("fisher") or {}
    assert fisher.get("ok") is True, f"fisher.ok が True でない: {fisher}"
    gap = fisher.get("gap")
    assert isinstance(gap, (int, float)) and gap <= 0.05, (
        f"fisher.gap は <= 0.05 であるべき（実際: {gap}）"
    )


def test_macro_v2_expectations_identity():
    mac = _load("macro_v2.json")
    exp = (mac.get("identities") or {}).get("expectations") or {}
    value, nominal, tp = exp.get("value"), exp.get("nominal"), exp.get("term_premium")
    assert None not in (value, nominal, tp), f"expectations に欠損: {exp}"
    assert abs(value - (nominal - tp)) < 1e-6, (
        f"expectations = nominal - term_premium が不成立: "
        f"{value} != {nominal} - {tp} = {nominal - tp}"
    )


def test_macro_v2_live_series_have_context():
    mac = _load("macro_v2.json")
    series = mac.get("series") or {}
    assert series, "macro_v2.series が空"
    bad = []
    for k, v in series.items():
        if v.get("data_status") != "live":
            continue
        ctx = v.get("context") or {}
        miss = [f for f in ("pct_rank", "z", "d20_z") if f not in ctx]
        if miss:
            bad.append(f"{k}: {miss}")
    assert not bad, f"live 系列で context(pct_rank/z/d20_z) を欠くもの: {bad}"


# ─────────────────────────── 天秤（relations）───────────────────────────
def test_relations_three_regions_series_length():
    rel = _load("relations.json")
    regions = rel.get("regions") or {}
    assert set(regions) == {"us", "eu", "jp"}, (
        f"relations.regions は us/eu/jp の 3 地域であるべき（実際: {sorted(regions)}）"
    )
    for reg in ("us", "eu", "jp"):
        s = (regions.get(reg) or {}).get("series") or []
        assert len(s) >= 200, f"relations.{reg}.series は 200 件以上であるべき（実際: {len(s)}）"


def test_relations_align_inner_join():
    rel = _load("relations.json")
    assert rel.get("align") == "inner_join", (
        f"relations.align は 'inner_join' であるべき（実際: {rel.get('align')!r}）"
    )


def test_relations_eu_jp_have_no_real_yield_or_term_premium():
    rel = _load("relations.json")
    regions = rel.get("regions") or {}
    for reg in ("eu", "jp"):
        v = regions.get(reg) or {}
        assert v.get("real_yield") is None, (
            f"relations.{reg}.real_yield は null であるべき（無料日次系列が無い）"
            f"（実際: {v.get('real_yield')!r}）"
        )
        assert v.get("term_premium") is None, (
            f"relations.{reg}.term_premium は null であるべき（実際: {v.get('term_premium')!r}）"
        )


def test_relations_erp_unavailable_with_reason():
    rel = _load("relations.json")
    erp = (rel.get("balance") or {}).get("erp") or {}
    assert erp.get("data_status") == "unavailable", (
        f"erp.data_status は 'unavailable' であるべき（実際: {erp.get('data_status')!r}）"
    )
    reason = erp.get("reason")
    assert isinstance(reason, str) and reason.strip(), (
        "erp.reason は空欄禁止（なぜ取得不能かを必ず書く）"
    )


def test_relations_regime_in_allowed_set():
    rel = _load("relations.json")
    regime = ((rel.get("balance") or {}).get("regime") or {}).get("regime")
    assert regime in REGIME_ALLOWED, (
        f"regime は {REGIME_ALLOWED} のいずれかであるべき（実際: {regime!r}）"
    )


# ─────────────────────────── ガンマ ───────────────────────────
def test_gamma_assumption_naive_dealer_with_note():
    g = _load("gamma.json")
    assert g.get("assumption") == "naive_dealer_convention", (
        f"gamma.assumption は 'naive_dealer_convention' であるべき（実際: {g.get('assumption')!r}）"
    )
    note = g.get("note")
    assert isinstance(note, str) and note.strip(), "gamma.note は空欄禁止（符号仮定を明示）"


def test_gamma_oi_and_0dte_are_separate_keys():
    g = _load("gamma.json")
    assert "gex_oi" in g, "gex_oi キーが無い"
    assert "gex_volume_0dte" in g, "gex_volume_0dte キーが無い（別キーで存在すべき、合算禁止）"


def test_gamma_0dte_state_matches_contract_availability():
    """0DTE の可用性は n_0dte_contracts に依存する（一時状態を不変条件に固定しない）。

    このフィードが当日満期(0DTE)を捕捉できるかは取得タイミングで変わる:
      - 週末/引け後スナップ → 最も近い満期が既に過ぎ n_0dte_contracts == 0 → 捕捉不能
      - 平日ライブ取得中     → 当日満期が実在し n_0dte_contracts > 0  → 捕捉可能
    build_gamma.py の分岐（_0dte_captured = n_0dte_contracts > 0）と一致させる。
    """
    g = _load("gamma.json")
    n = g.get("n_0dte_contracts")
    assert isinstance(n, int) and n >= 0, f"n_0dte_contracts が非負整数でない: {n!r}"
    val = g.get("gex_volume_0dte")
    status = g.get("gex_volume_0dte_status")
    reason = g.get("gex_volume_0dte_reason")

    if n == 0:
        # 捕捉不能: null + unavailable + reason（0 と誤読させない）
        assert val is None, (
            f"n_0dte_contracts==0 なら gex_volume_0dte は null であるべき（実際: {val!r}）"
        )
        assert status == "unavailable", (
            f"n_0dte_contracts==0 なら status は 'unavailable' であるべき（実際: {status!r}）"
        )
        assert isinstance(reason, str) and reason.strip(), (
            "n_0dte_contracts==0 のとき reason は空欄禁止（なぜ捕捉できないかを明示）"
        )
    else:
        # 捕捉可能: 数値 + live（当日満期が実在）
        assert isinstance(val, (int, float)), (
            f"n_0dte_contracts>0 なら gex_volume_0dte は数値であるべき（実際: {val!r}）"
        )
        assert status == "live", (
            f"n_0dte_contracts>0 なら status は 'live' であるべき（実際: {status!r}）"
        )


def test_gamma_coverage_jp_eu_unavailable():
    g = _load("gamma.json")
    cov = g.get("coverage") or {}
    for reg in ("jp", "eu"):
        assert cov.get(reg) == "unavailable", (
            f"gamma.coverage.{reg} は 'unavailable' であるべき（米国限定層）"
            f"（実際: {cov.get(reg)!r}）"
        )


# ─────────────────────────── 説明文（キャプション）───────────────────────────
def test_every_figure_has_a_caption():
    """index.html の各図に「この図」で始まるキャプションが存在する。

    未来の自分が誤読しないための引き継ぎ。消えたら検出する。
    """
    html = _read_index()
    assert "const cap=" in html, "caption ヘルパ (const cap=) が消えている"
    assert 'class="rel-cap"' in html, "キャプション DOM (rel-cap) が消えている"
    n_fig = html.count("この図")
    assert n_fig >= 10, f"図キャプション（『この図』）が {n_fig} 件しかない（期待 >= 10）"


def test_captions_cite_sources():
    """キャプションに出典を示す文字列が含まれている。

    出典行（出典・算出）の数が図キャプション数を下回らないこと＝各図が出典を伴う。
    加えて主要出典トークンが本文に存在すること。
    """
    html = _read_index()
    n_fig = html.count("この図")
    n_src = html.count("出典")
    assert n_src >= n_fig, (
        f"出典行 {n_src} 件 < 図 {n_fig} 件。出典を欠くキャプションがある疑い。"
    )
    for token in ("FRED", "CBOE", "CFTC"):
        assert token in html, f"キャプションに出典トークン {token} が見当たらない"


# ─────────────────────── 銘柄件数の劣化検知 ───────────────────────
def test_meta_counts_match_actual_lengths():
    """meta.counts が各カテゴリの実配列長と一致する（件数の自己申告が実体とズレない）。"""
    data = _load("data.json")
    counts = (data.get("meta") or {}).get("counts") or {}
    markets = data.get("markets") or {}
    bad = []
    for cat, n in counts.items():
        actual = len(markets.get(cat, []))
        if n != actual:
            bad.append(f"{cat}: meta.counts={n} != actual={actual}")
    assert counts, "meta.counts が無い"
    assert not bad, f"meta.counts と実配列長の不一致: {bad}"


def test_equity_constituent_count_above_min():
    """各 equity タブの構成銘柄数が下限を下回らない。乖離率(目標比)を必ず出力する。

    下限は現在値ベースの暫定基準。目標(full index)との乖離はデータ品質の可視化であって
    それ自体は FAIL ではない（下限割れのみ FAIL）。
    """
    data = _load("data.json")
    markets = data.get("markets") or {}
    report, failed = [], []
    for tab in EQUITY_TABS:
        n = _constituent_count(markets.get(tab, []))
        mn = EQUITY_MIN_COUNTS[tab]
        tgt = EQUITY_TARGET_COUNTS[tab]
        dev = round((n - tgt) / tgt * 100, 1)          # 目標比の乖離率（負=不足）
        line = f"{tab}: count={n} min={mn} target={tgt} 乖離={dev:+.1f}%"
        report.append(line)
        if n < mn:
            failed.append(line)
    # 乖離率は常に可視化（成功時も出力に残す）
    summary = " | ".join(report)
    assert not failed, f"構成銘柄数が下限割れ: {failed} || 全体: {summary}"
    print("\n[universe] " + summary)


def test_dow30_constituents_do_not_exceed_30():
    """dow30 の構成銘柄数は 30 以下（上限）。31 は指数本体(^DJI)か入替前銘柄の混入。

    ^DJII 等の index proxy は別枠（構成銘柄カウントから除外済み）。構成銘柄が 30 を超えたら
    それは本当の混入なので FAIL させる。
    """
    data = _load("data.json")
    rows = (data.get("markets") or {}).get("dow30", [])
    n = _constituent_count(rows)
    extras = sorted(r.get("symbol") for r in rows
                    if isinstance(r, dict) and str(r.get("symbol", "")).startswith("^"))
    assert n <= DOW30_MAX_CONSTITUENTS, (
        f"dow30 構成銘柄数 {n} > {DOW30_MAX_CONSTITUENTS}（指数本体/入替前銘柄の混入疑い）。"
        f"index proxy(除外済) = {extras}"
    )


def test_meta_universe_recorded_and_consistent():
    """meta.universe に4 equity タブの count/target/capture_pct が記録され、実体と一致する。

    target(full index) を別フィールドとして恒久記録し、UI と突き合わせられるようにする。
    """
    data = _load("data.json")
    uni = (data.get("meta") or {}).get("universe") or {}
    markets = data.get("markets") or {}
    assert set(uni.keys()) == set(EQUITY_TABS), (
        f"meta.universe は 4 equity タブを持つべき（実際: {sorted(uni.keys())}）"
    )
    bad = []
    for tab in EQUITY_TABS:
        rec = uni.get(tab) or {}
        actual = _constituent_count(markets.get(tab, []))
        if rec.get("count") != actual:
            bad.append(f"{tab}: universe.count={rec.get('count')} != actual={actual}")
        if rec.get("target") != EQUITY_TARGET_COUNTS[tab]:
            bad.append(f"{tab}: universe.target={rec.get('target')} != {EQUITY_TARGET_COUNTS[tab]}")
    assert not bad, f"meta.universe が実体/目標と不整合: {bad}"


# ─────────────────── サイレント fallback 禁止 / ユニバース健全性 ───────────────────
def test_meta_fallbacks_is_recorded_list():
    """meta.fallbacks が存在し list である（fallback を静かに使わない土台）。

    0 件なら健全。発動時は {source, reason, ...} を持つ。
    """
    data = _load("data.json")
    fbs = (data.get("meta") or {}).get("fallbacks")
    assert isinstance(fbs, list), "meta.fallbacks は list であるべき（サイレント fallback 禁止の記録先）"
    for f in fbs:
        assert f.get("source") and f.get("reason"), f"fallback 記録に source/reason が無い: {f}"


def test_sp500_fallback_recorded_not_silent():
    """S&P500 が full を取れない(構成 < 400)とき、必ず meta.fallbacks に記録される。

    静かに 102 fallback へ落ちる状態を禁止する。403 根治が効いていれば構成 >= 400 で
    fallback 0 件。全ソース障害時のみ fallback だが、その時は必ず記録されること。
    """
    data = _load("data.json")
    meta = data.get("meta") or {}
    cnt = (meta.get("universe") or {}).get("sp500", {}).get("count", 0)
    if cnt < 400:
        rec = [f for f in (meta.get("fallbacks") or [])
               if "sp500" in str(f.get("source", ""))]
        assert rec, (
            f"sp500 構成 {cnt} < 400 なのに meta.fallbacks に sp500 記録が無い（サイレント fallback）"
        )


def test_meta_universe_has_source_mode_and_failures():
    """meta.universe の各 equity タブが source_mode と fetch_failures を持つ。

    上場廃止/入替を黙って件数だけ減らさない（fetch_failures に列挙）。
    """
    data = _load("data.json")
    uni = (data.get("meta") or {}).get("universe") or {}
    valid_modes = {"dynamic", "curated_full", "curated_subset"}
    bad = []
    for tab in EQUITY_TABS:
        rec = uni.get(tab) or {}
        if rec.get("source_mode") not in valid_modes:
            bad.append(f"{tab}: source_mode={rec.get('source_mode')!r}")
        if not isinstance(rec.get("fetch_failures"), list):
            bad.append(f"{tab}: fetch_failures が list でない")
    assert not bad, f"meta.universe の source_mode/fetch_failures 不備: {bad}"


def test_meta_nan_report_present():
    """meta.nan_report が 4 equity タブ分あり、件数フィールドを持つ（計測の記録）。"""
    data = _load("data.json")
    nan = (data.get("meta") or {}).get("nan_report") or {}
    assert set(nan.keys()) == set(EQUITY_TABS), (
        f"meta.nan_report は 4 equity タブを持つべき（実際: {sorted(nan.keys())}）"
    )
    for tab in EQUITY_TABS:
        rec = nan.get(tab) or {}
        for k in ("constituents", "price_null", "chart_unavailable"):
            assert isinstance(rec.get(k), int), f"nan_report.{tab}.{k} が int でない"
