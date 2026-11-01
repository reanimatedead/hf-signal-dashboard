"""screener.calc — データを含まない計算式だけのパッケージ（旧 marketcalc）。

公開ダッシュボード（fetch_signals.py・pipeline/・tools/。互換の marketcalc/ 経由）と
ローカル実行（screener.japan / screener.us）の両方がここを使う。式を直すのはこのディレクトリだけ。
- ind:        CCI / ボリンジャーバンド / 売買判定（日足）
- fund_us:    米国株 EDGAR 決算から指標（F・魔法の公式・残余利益モデル）
- value:      残余利益モデル（理論PBR）・F スコア集計・一時利益の目印
- events:     シグナル後 N 日の値動き検証（イベントスタディ）
- contracts:  外部データの契約テスト用の小さな判定関数
データ・キー・ファイル入出力は持たない（呼ぶ側が渡す）。
"""
__version__ = "1.0.0"
