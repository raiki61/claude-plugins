# /catchup の準備（`/catchup setup` と打たれたときに読む）

/catchup（1 件の PR などについて、前回から何が起きたかを 1 枚の HTML のページに描くコマンド）のページ（`~/.cache/attention/` の下の HTML）は、VS Code の Remote-SSH の窓で、拡張 Simple HTML Viewer が開く。この文書はその準備の中身。

1. `bash "${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/catchup.py" --setup` を走らせる（`${CLAUDE_PLUGIN_ROOT}` はこのプラグインの置き場）。何も変えずに確かめるだけなら `--setup --check`。
2. 出力をそのまま返す。窓が繋がっていない（VS Code を閉じている）と拡張は入れられないので、そのときは繋いでからもう一度と返す。

機械がすること:

1. 生きている VS Code の窓を探す（`code --status` が通る socket）。このマシンに `~/.vscode-server` が無ければ（Remote-SSH で繋いだことの無いマシン）、何も書かずに訳を返して終わる。
2. 拡張が `~/.vscode-server/extensions` に無ければ、`code --install-extension austin-spagnolo.simple-html-viewer` で入れる。
3. `~/.vscode-server/data/Machine/settings.json` に 2 つを足す: `workbench.editorAssociations` の `"**/.cache/attention/**/*.html": "simpleHtmlViewer.preview"` と、`"simpleHtmlViewer.autoRefresh": "onFileChange"`。ほかのキーは消さず、書く前に同じ階層へ控え（`settings.json.bak-<日時>`）を置く。注記（`//`）の有るファイルは書き直さず、足す行を示す。
4. 見本のページを描いて開く。
5. したことと、まだ足りない物を並べる。
