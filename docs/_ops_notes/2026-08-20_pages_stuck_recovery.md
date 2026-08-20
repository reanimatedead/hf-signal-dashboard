# 2026-08-20 Pages deploy スタック復旧

## 事象
- 2026-08-11 以降 data.json が更新停止、`verify_live` が freshness (213h > 48h) で FAIL。
- monitor.yml は 8/12 から Issue #4 起票済み（外形監視は正常動作）。

## 真因
- deploy.yml run #31510071079 の `full` ジョブが 8/11 16:00Z から 8 日間 queued 滞留。
- `concurrency: group=pages, cancel-in-progress: false` により後続 scheduled run が全て cancelled。
- 取得コードは無罪（collect.yml は 8/16 まで success を継続）。

## 修正
1. `concurrency.cancel-in-progress: true` に反転（詰まりが自己回復）。
2. `tools/gate_thresholds.py` 新設 — 48h / 90% を集約。
3. `tools/assert_gen_health.py` 新設 — 生成時 hard assert（freshness<48h & equity_ready>=90%）。deploy.yml full/corr_refresh に配線。
4. deploy.yml full/corr_refresh + collect.yml に `if: failure()` の auto Issue 起票を追加。
5. `process_market` に chart_api heal（バッチ欠落を per-symbol リトライ）。
6. NASDAQ100 curated: ANSS(SNPS 買収→404)/EA(heal 失敗) を除外、PLTR/APP/ARM を追加。

## 復旧確認
- deploy.yml full run 32323298590 = success
- verify_live: age=11.0h / equity ready 99.7% / 全 layer 200
- monitor.yml 32372774566 = success

## 監視ポイント
- 次の schedule (00:00 JST daily) が緑で通ること。
- monitor.yml が 2h 間隔で緑継続すること。
- NASDAQ100 count が >=91 で推移すること（heal ログで欠落銘柄が可視化されるので、
  同じ銘柄が 3 run 連続で dead ならその curated 更新が次のアクション）。

## 残存リスク
- curated dict は買収/上場廃止のたび手動更新（自動置換はしない設計）。
- EA は Yahoo API 200 だが heal 時空応答 — 取引再安定で復帰候補。
- nikkei225 の 9613.T が欠落継続中（別途調査）。

## commit
- fb23937 fix(ci): unstick pages deploy and force update-job to self-fail on stale/incomplete payload
- b80a0ac feat(fetch): heal batch-missing equity symbols via chart_api fallback
- 18d759f fix(universe): refresh NASDAQ100 curated dict (ANSS/EA delist → +PLTR/APP/ARM)
