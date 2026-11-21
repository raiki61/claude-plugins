"""ファイルを書きかけで残さない書き方。/catchup のページ・/reflect・/milestone-map・/my-turn の記録・steps-prep.py の受け渡しで共用。"""

import os
import pathlib
import shutil
import tempfile


def write_text(path, text):
    """同じ階層の一時ファイルに書いてから置き換える。拡張の autoRefresh（onFileChange）や後の段が書きかけを読まない。"""
    path = pathlib.Path(os.path.realpath(path))  # symlink の設定（dotfiles 管理）は、置き換えて普通の file にせず、指す先に書く
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", dir=str(path.parent))
    try:
        with open(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        if path.exists():
            shutil.copymode(path, tmp)  # mkstemp は 0600 で作るので、元の権限を引き継ぐ
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
