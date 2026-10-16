# claude-plugins

[![test](https://github.com/raiki61/claude-plugins/actions/workflows/test.yml/badge.svg)](https://github.com/raiki61/claude-plugins/actions/workflows/test.yml)

Claude Code のプラグインを配るマーケットプレイス（名前は `raiki61`）。レビューや調べものを収束するまで回す道具、GitHub へ投稿する前の検査、並行作業の見渡し、作業ごとに Claude Code の会話を立てて頼む道具などを入れている。

## プラグイン

配るプラグインは 8 本。使う物だけを、1 本ずつ入れる。

| プラグイン | 何をするか | 説明 |
|---|---|---|
| **convergence-loops** | レビュー・調査・診断・文書の初見読みを、収束するまで回す | [README](convergence-loops/README.md) |
| **gates** | GitHub への投稿と書いた文書を、初見の読み手が読めるまで止める | [README](gates/README.md) |
| **attention** | 並行作業のどれが自分の番か、どこで止まっていたかを出す | [README](attention/README.md) |
| **graphloops** | convergence-loops のレビューと調査を、機械が回す版 | [README](graphloops/README.md) |
| **works** | 修正の依頼を、AI の生産ライン darkfactory に回す | [README](works/README.md) |
| **works-factory** | 修正の依頼を、別のリポジトリの工場 works-factory に回す | [SKILL.md](works-factory/skills/works-factory/SKILL.md) |
| **works-dispatch** | 作業ごとに Claude Code の会話を立てて頼み、要約を返させる | [README](works-dispatch/README.md) |
| **tiers** | プラグインが要る外の道具がそろっているかを点検する | [README](tiers/README.md) |

## 入れ方

Claude Code の中で、マーケットプレイスを足してから、使うプラグインを入れる。

```
/plugin marketplace add raiki61/claude-plugins
/plugin install works-dispatch@raiki61
```

端末からなら、次の 2 行でも同じ。

```bash
claude plugin marketplace add raiki61/claude-plugins
claude plugin install works-dispatch@raiki61
```

`@raiki61` はマーケットプレイスの名前。ほかのプラグインに依存するプラグインを入れると、依存先も一緒に入る（例: works-dispatch を入れると tiers も入る）。新しい版にするには `claude plugin marketplace update raiki61` の後に `claude plugin update <プラグイン>@raiki61` を打ち、Claude Code を起こし直す。

## 要る道具の段

プラグインによっては、Claude Code のほかに外の道具が要る。要る道具を 4 つの段に分けている。上の段は下の段の道具も要る。

- 段 0: Claude Code だけ。
- 段 1: gh（GitHub の CLI）が入っていて、ログイン済み。
- 段 2: herdr（端末を作業場ごとに分け、中の Claude Code の会話を外から操作する道具）が動いている。アカウントごとに別の命令で Claude Code を起こすなら、その命令も。
- 段 3: Archon（AI の作業の流れを順に回す道具）。

要る段は、各プラグインの README の「要る物」に書く（今書いてあるのは works-dispatch の段 2）。道具がそろっているかは、tiers を入れて `/tiers:check` で点検できる。足りない物と入れ方を出すだけで、何も入れない。

## このリポジトリを直す人へ

試験の回し方と決まりは [CONTRIBUTING.md](CONTRIBUTING.md)。ライセンスは MIT（[LICENSE](LICENSE)）。
