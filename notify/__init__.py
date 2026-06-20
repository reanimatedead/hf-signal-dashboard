"""notify/ — Phase 1.6 即時通知 + 改竄不能ログ.

SPEC_NOTIFY.md と一対。
- chain: append-only ハッシュチェーン台帳 (sha256)
- triggers: look-ahead 厳禁の ENTRY/EXIT 判定
- bus: osascript ローカル通知 + ntfy.sh への HTTP POST + queue/retry/dedup
- config: ~/hf-signal-dashboard/config.local の読込み (不在時は通知無効)
- receiver: 60 秒ループ (launchd 経由で常駐)

Phase 2 (学習) / Phase 3 (勝敗判定) は本パッケージには持ち込まない。
"""
