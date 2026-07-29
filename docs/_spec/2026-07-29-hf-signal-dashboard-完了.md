---
title: hf-signal-dashboard 依頼3件完了とソースヘッジ確立
date: 2026-07-29
tags: [taka-automation, hf-signal-dashboard, macro, data-source-hedge, ci-gate, claude-code]
related: ["[[hf-signal-dashboard]]", "[[fx-analysis-system]]", "[[taka-instruction-preflight]]", "[[borrowed-infrastructure-principle]]", "~/hf-signal-dashboard/DATA_CONTRACT.md（リポジトリ直下・repo内コピーからは ../../DATA_CONTRACT.md）"]
source: claude-chat
---

# 依頼3件を完了し、分析層をYahoo非依存にした

## 要点

**依頼3件（すべて本番反映済み）**

| 依頼 | 開始時 | 現在 |
|---|---|---|
| インジケータが出ない銘柄がある | 29/368（7.9%） | **368/368（100%）** |
| リンク先が機能しない | 非ティッカー20件が404 | **0件** |
| 債券利回り×株価を日欧米で | 存在しない | **3地域260日・天秤4部品** |

**途中で追加した層**

- マクロ層: FRED 16系列。分解恒等式を検算コードに埋め込み（名目4.71 = 実質2.43 + 期待2.26、gap 0.02）
- ガンマ層: CBOE公開チェーン。GEX −235億ドル/1%、ゼロガンマ 7,455、現値はその下＝増幅ゾーン
- 天秤層: 相関レジーム −0.414（成長ショック主導＝天秤機能中）、感応度β、四半期末リバランス、パーセンタイル
- EU利回り: ECB 2Y/10Y/30Y（2.71 / 3.16 / 3.60）
- 相関: 10×10 → 12×12、align inner_join を明示

**配信構造の転換**

```
ブランチに毎日コミット  →  Actions artifact 配信（git履歴に積まない）
data.json 1.31MB 単一   →  242KB + タブ別遅延ロード
テスト 258              →  283
外形監視 なし           →  monitor.yml 2時間ごと・失敗でメール＋Issue自動起票
```

**ソースヘッジ（本日の主作業）**

Yahoo非依存: 天秤層 / マクロ層 / ガンマ層 / 金利（FRED・財務省・ECB）/ IMM / valuation / money_flow / VIX
Yahoo依存が残る: MOVE・個別株368・FX・crypto・EU株指数・相関の株式ラベル

→ いずれも無料の非Yahoo日次代替が存在しないことを実測で確認済み。

## 決定事項

- **US金利を FRED（DGS2/10/30）に切替、yfinance を fallback に残置。** 天秤層はFRED・一覧表はYahooという分裂を解消。同じ金利を別ソースから取る状態は冗長ではなく矛盾だった
- **VIX を FRED VIXCLS に切替、yfinance ^VIX を fallback。** linkはYahooクォートページのまま（データ源とリンク先は別属性）
- **有料APIは全て見送り。** tradingviewapi.com は TradingView 非公式のスクレイプ業者（RapidAPI個人出品者）。EODHD $19.99 は個人利用限定で公開配信は契約違反。商用は $299/月
- **Stooq は不採用。** proof-of-work で全プログラム的アクセスを遮断。突破は技術的に可能だが、明示的な拒否意思の回避は yfinance のグレーゾーンより悪い立場になる
- **degrade方針を採用。** 障害時は古い値を保持せず unavailable + reason を出す。「古い値を最新と誤認させない」で全層一貫
- **被覆率の閾値は health_gate 90% に一本化。** 量の判定＝health_gate、質の判定＝contract test と役割を分離
- **費用は ¥0 のまま。** Actionsはパブリックリポジトリで無制限、Pages帯域は上限の0.2%、ローカル50GBで最短19年分

## 盲点・リスク

**構造的に残るもの**

- **個別株368銘柄・FX・cryptoは無料の非Yahoo代替が存在しない。** 368銘柄の日次を無料で配る業者はいない。ここは「依存している」と明記して受け入れる領域
- **MOVE は FRED に存在しない**（実測確認）。Yahoo単一依存
- **EU株 STOXX50E の日次**: ECBは月次（最新2026-06）、FREDは四半期（最新2025-10）、Stooqはbot遮断。日次の無料代替が未発見
- **ERPは実装不能**: 指数の日次EPSに無料の信頼ソースがない。Shillerミラーは2024-09で更新停止

**未検証**

- **chart APIフォールバックが本番で一度も発火していない。** オフライン実証のみ。次の劣化時が実地テストになる
- **check_links が診断ツールとして機能していない**（ok=3 / warn=347）。99%が警告では情報を持たない。一次出典4ドメインに限定すべき

**運用上**

- mini のIPが Yahoo に 429 されている（本日の調査での過剰アクセス）。ローカルでの fetch_signals.py 実行は間隔を空ける
- full の実行時間が約6分。Pagesタイムアウト10分に対し余裕4分。これ以上層を足すと当たる

## 次アクション

- [ ] 2026-08-02以降: corr.yml / update_signals.yml を削除（deploy.ymlに統合済み、DATA_CONTRACTに記載済み）
- [ ] 2026-10-26: decisions.jsonl の review_date。「相関が+0.20を超えたら天秤機能中という読みは外れ」
- [ ] 次に触るとき: check_links を一次出典4ドメイン（MoF/ECB/CFTC/FRED）に限定
- [ ] v3候補: ブレッドス（SP500 103銘柄を既に保持＝追加取得ゼロ。最も費用対効果が高い）
- [ ] v3候補: 銅金比率、CFTC株価指数先物建玉
- [ ] 明日以降の定期実行（毎日00:00 JST）が通ることを monitor.yml で確認

## 障害記録

```
19:05  Pages のソースが Deploy from a branch に戻りサイト404（1時間15分停止）
       原因: collect.yml の push が経路と疑われる（未確定）
       対策: deploy.yml に configure-pages@v6 を追加し build_type=workflow を毎回再宣言
20:35  米国株176件のNaN劣化でゲート停止。healが0件回復
       yfinance一括経路のみ劣化、Yahoo chart API直叩きは正常だった
       48時間後に自然回復。chart APIフォールバックを配備（未実地発火）
```

**両方ともゲートが劣化データの配信を阻止した。** 契約テストとhealth_gateがartifactアップロード前にあるため、壊れたデータは一度も公開されていない。

## 学習メモ（学習#29）

**Claudeの指示ミスが8件発生し、全てゲートまたはClaude Codeの実測が止めた**

1. index.html と docs/index.html の取り違え
2. fredgraph `?g=qLC` を未検証で記載（実際はGDPページ）
3. `|| echo OK` で誤合格を発生（ファイル不在と不一致を区別できない）
4. Task 1の完了条件に被覆率を入れず、実装漏れを合格させた
5. 0DTE=0 という一時観測を不変条件としてテストに固定
6. contract test 95% と health_gate 90% の二重基準を作った
7. yfinance劣化を「構造的」と誤診断（実際は48時間の一時障害）
8. 層別Yahoo依存マップが誤り（金利・FXを非依存と記載。source未実測）

**特に6・7・8はClaude Codeが実測で押し返した。** 「切り替える対象が既にFREDだ」「実測すると分類が違う」と。指示を出す側が間違えても、実装する側が実物を見て止める構造が5回機能した。

**事前検証ハーネス（規則1〜9）を確立**

1. 実物を叩いていない識別子を書かない
2. 検証コマンドが誤合格しない形か（`test -f` → `grep -c`、`|| echo OK` 禁止）
3. 完了条件が依頼の言葉を直接測っているか
4. 制約が物理か選択かを区別しているか
5. 動いているものを退行させていないか
6. 会話内で自分が述べた制約と矛盾していないか
7. 修正パッチの波及先を洗ったか
8. 観測した状態を不変条件としてテストに固定しない
9. 同一の指標に複数の閾値を置かない

**設計原則として確立したもの**

- **フラグではなく中身を測る。** `chart_status: ready` の件数だけ見て、BBの帯が空でも合格させた。upper > basis > lower を実物で検証する
- **古い値を保持せず unavailable + reason を出す。** 3日前のGEXを現在値として表示するのは誤情報
- **falsifierを残す。** 反証条件がないと都合のいい記憶だけが残る確認バイアス装置になる
- **量の判定と質の判定を混ぜない。** 被覆率はゲート、不変条件は契約テスト
- **「二重化」を名乗る前に提供者が別か確認する。** yfinance と chart API は経路が2本でも同じYahooで、単一障害点のままだった
