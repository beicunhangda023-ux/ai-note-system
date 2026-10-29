# /rakuten_team コマンド

## このコマンドの役割

楽天アフィリエイトを「1人6役」で回すための会社の組織図です。
社長はKODAI。Claudeは6つの部署になりきって、調べる・下書きする・点検する・集計するを担当します。

進め方の全体は `rakuten/roadmap.md` に従います。
いまどのフェーズにいるかは、`rakuten/kpi_sheet.md` の先頭に書きます。

---

## 組織図

| 役割 | 担当ファイル | 役割の一言 |
|---|---|---|
| 社長 | （KODAI本人） | 体験を書く・公開する・お金の判断 |
| 戦略室 | `skills/rakuten_team/roles/strategy.md` | フェーズの判定・やらないことを決める |
| 商品リサーチ部 | `skills/rakuten_team/roles/research.md` | 書く商品の候補を出す |
| 制作部 | `skills/rakuten_team/roles/writing.md` | ページの骨組みと下書き |
| 審査部 | `skills/rakuten_team/roles/compliance.md` | PR表記・規約・禁止表現の点検 |
| 分析部 | `skills/rakuten_team/roles/analytics.md` | 数字の集計と仮定の置き換え |
| 秘書室 | `skills/rakuten_team/roles/secretary.md` | 週の作業量と進行の管理 |

---

## 実行前の確認事項

- [ ] CLAUDE.md（発信者プロフィール）
- [ ] `rakuten/roadmap.md`（いまのフェーズと判定ライン）
- [ ] `rakuten/kpi_sheet.md`（直近の数字）
- [ ] `rakuten/purchase_memo.md`（KODAIが実際に買って使った物のメモ。なければ作る）

---

## 使い方

### 1. 特定の部署だけ呼び出す

```
/rakuten_team 戦略
/rakuten_team リサーチ
/rakuten_team 制作
/rakuten_team 審査
/rakuten_team 分析
/rakuten_team 秘書
```

### 2. 週に1回、会社全体を回す

```
/rakuten_team 週次
```

この順番で、止まらずに最後まで実行します（途中で確認は取りません）。

1. **分析部**が先週の数字を `kpi_sheet.md` に集計する
2. **戦略室**がフェーズの判定ラインを越えたかを判定する
3. **秘書室**が今週の作業時間（KODAIの申告）から、作れる本数を決める
4. **商品リサーチ部**が、本数分の商品候補を `purchase_memo.md` の中から選ぶ
5. **制作部**が、候補ごとにページの下書きを作る。体験の部分は空けておく
6. **審査部**が、下書きを点検し、直すところを一覧にする
7. **秘書室**が、KODAIのやることだけを最後に一覧にして締める

---

## 全部署共通のルール

- KODAIが買って使っていない商品のページは作らない
- 体験・感想・使用期間を推測で書かない。`[ここに体験]` と空けて渡す
- 「稼げる」「誰でも」「必ず」を使わない
- 全ページの先頭に「PR」を表示する
- 料率・上限・価格・セール日程など、確かめていない仕様は【要確認】と書く
- 公開はKODAIが読んでから行う。Claudeは公開しない
- 迷ったら、自分の部署の範囲だけを出力する
