"""notify.chain — append-only / hash chain / EXIT 欠損検知 (SPEC_NOTIFY §3, §10.3, §10.4)."""
import json
import pathlib
import pytest

ch = pytest.importorskip(
    "notify.chain",
    reason="Agent C 未実装。notify/chain.py を作ると緑になる。",
)


@pytest.fixture
def tmp_chain_path(tmp_path):
    return tmp_path / "notifications.jsonl"


def _entry(symbol="AAPL", side="long", edge=72, price=100.0):
    return {
        "kind": "ENTRY",
        "symbol": symbol,
        "side": side,
        "bar_tf": "1d",
        "bar_ts": "2026-06-20T00:00:00Z",
        "price": price,
        "edge_score": edge,
        "entry_ref": None,
        "pattern": {"regime": "high_vol", "distortion": "high"},
        "size_pct": 0.14,
        "exit_targets": {"take_profit_pct": 3.5, "stop_loss_pct": -1.8},
        "realized_pct": None,
    }


def _exit_tp(entry_ref, symbol="AAPL", price=103.5, realized=3.5):
    return {
        "kind": "EXIT_TP",
        "symbol": symbol,
        "side": "long",
        "bar_tf": "1d",
        "bar_ts": "2026-06-25T00:00:00Z",
        "price": price,
        "edge_score": None,
        "entry_ref": entry_ref,
        "pattern": {"regime": "high_vol", "distortion": "high"},
        "size_pct": 0.14,
        "exit_targets": {"take_profit_pct": 3.5, "stop_loss_pct": -1.8},
        "realized_pct": realized,
    }


# ── 構造 ────────────────────────────────────────────────
def test_chain_append_returns_hash_fields(tmp_chain_path):
    c = ch.Chain(tmp_chain_path)
    row = c.append(_entry())
    for k in ("event_id", "ts_utc", "prev_hash", "curr_hash", "notice"):
        assert k in row, f"row missing {k}"
    assert row["curr_hash"] != row["prev_hash"]
    assert row["notice"] == "事実記録 / not investment advice"


def test_chain_genesis_prev_hash_all_zeros(tmp_chain_path):
    c = ch.Chain(tmp_chain_path)
    row = c.append(_entry())
    assert row["prev_hash"] == "0" * 64, "genesis prev_hash must be 64 zeros"


def test_chain_curr_hash_is_sha256_of_prev_plus_payload(tmp_chain_path):
    import hashlib
    c = ch.Chain(tmp_chain_path)
    row = c.append(_entry())
    # Reproduce: canonical body without curr_hash/prev_hash → sha256(prev + body)
    body = {k: v for k, v in row.items() if k not in ("curr_hash", "prev_hash")}
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True)
    expected = hashlib.sha256((row["prev_hash"] + canonical).encode("utf-8")).hexdigest()
    assert row["curr_hash"] == expected


# ── verify() ────────────────────────────────────────────
def test_chain_verify_passes_after_many_appends(tmp_chain_path):
    c = ch.Chain(tmp_chain_path)
    a = c.append(_entry(symbol="AAPL"))
    b = c.append(_entry(symbol="MSFT", edge=75, price=200.0))
    c.append(_exit_tp(a["event_id"], symbol="AAPL"))
    c.append(_exit_tp(b["event_id"], symbol="MSFT", price=206.0))
    ok, broken_at, reason = c.verify()
    assert ok is True
    assert broken_at is None


def test_chain_detects_tampered_row(tmp_chain_path):
    c = ch.Chain(tmp_chain_path)
    c.append(_entry(symbol="AAPL"))
    c.append(_entry(symbol="MSFT", edge=75, price=200.0))
    # 中間行を直接書き換える (curr_hash も含む)
    lines = tmp_chain_path.read_text().splitlines()
    row = json.loads(lines[0])
    row["symbol"] = "ATTACK"
    lines[0] = json.dumps(row, ensure_ascii=False)
    tmp_chain_path.write_text("\n".join(lines) + "\n")
    # 再オープン → verify 失敗
    c2 = ch.Chain(tmp_chain_path)
    ok, broken_at, _ = c2.verify()
    assert ok is False
    assert broken_at is not None


def test_chain_detects_row_deletion(tmp_chain_path):
    c = ch.Chain(tmp_chain_path)
    c.append(_entry(symbol="AAPL"))
    c.append(_entry(symbol="MSFT", edge=75, price=200.0))
    c.append(_entry(symbol="GOOG", edge=78, price=140.0))
    # 中間行を削除
    lines = tmp_chain_path.read_text().splitlines()
    del lines[1]
    tmp_chain_path.write_text("\n".join(lines) + "\n")
    c2 = ch.Chain(tmp_chain_path)
    ok, _, _ = c2.verify()
    assert ok is False


def test_chain_detects_row_insertion(tmp_chain_path):
    c = ch.Chain(tmp_chain_path)
    a = c.append(_entry(symbol="AAPL"))
    b = c.append(_entry(symbol="MSFT", edge=75, price=200.0))
    # 中間に偽の ENTRY を挿入 (prev_hash も書き換えてリンクを偽装)
    lines = tmp_chain_path.read_text().splitlines()
    forged = json.loads(lines[1])
    forged["symbol"] = "FAKE"
    forged["prev_hash"] = a["curr_hash"]
    # curr_hash は対応せず、もちろん検証で落ちる
    lines.insert(1, json.dumps(forged, ensure_ascii=False))
    tmp_chain_path.write_text("\n".join(lines) + "\n")
    c2 = ch.Chain(tmp_chain_path)
    ok, _, _ = c2.verify()
    assert ok is False


# ── EXIT 欠損検知 ──────────────────────────────────────
def test_unmatched_entries_lists_only_open_entries(tmp_chain_path):
    c = ch.Chain(tmp_chain_path)
    a = c.append(_entry(symbol="AAPL"))
    b = c.append(_entry(symbol="MSFT", edge=75, price=200.0))
    # AAPL だけ EXIT_TP
    c.append(_exit_tp(a["event_id"], symbol="AAPL"))
    open_ = c.unmatched_entries()
    syms = [r["symbol"] for r in open_]
    assert syms == ["MSFT"], f"only MSFT should be unmatched; got {syms}"


def test_exit_missing_entry_ref_raises(tmp_chain_path):
    c = ch.Chain(tmp_chain_path)
    bad = _exit_tp(entry_ref=None)
    with pytest.raises(ValueError):
        c.append(bad)


def test_exit_with_unknown_entry_ref_raises(tmp_chain_path):
    c = ch.Chain(tmp_chain_path)
    c.append(_entry(symbol="AAPL"))
    bad = _exit_tp(entry_ref="nonexistent-id")
    with pytest.raises(ValueError):
        c.append(bad)


# ── append-only 保証: API に update/delete が無いこと ───
def test_chain_has_no_update_or_delete_api():
    forbidden = ("update", "delete", "patch", "rewrite", "truncate")
    public = [n for n in dir(ch.Chain) if not n.startswith("_")]
    bad = [n for n in public if any(f in n.lower() for f in forbidden)]
    assert not bad, f"forbidden mutator methods exposed: {bad}"
