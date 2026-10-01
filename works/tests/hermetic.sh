# shellcheck shell=sh
# 試験の入口（tests/run.sh・dev/tdd-suite.sh）が . で読む。試験を走らせる run（dev の殻 dogfood.sh・use.sh・archon.sh・
# real-run.sh と包み）が export する変数を、試験の子に継がせない（tox が既定で env を隔離するのと同じ考え）。
# 継がせると、既定の振る舞いを見る試験が外の run の値（包みの札・Context7 の口・claude の版など）で割れる。
# 外す名の一覧はここ 1 か所。殻に export を足したらここにも足す。WORKS_DEV_HOME と WORKS_RUN_PLACE（包みが Bash を持つ役の子に立てる run ごとの置き場。adapter.RUN_PLACE_ENV）は試験の置き場なので残す。
for _works_env in \
  WORKS_DEV_ADAPTER WORKS_DEV_MODEL WORKS_DEV_ARCHON WORKS_DEV_NO_AUTH \
  WORKS_CONTEXT7 WORKS_CONTEXT7_MCP \
  WORKS_USE_HOME WORKS_USE_SH WORKS_WRAPS_DIR WORKS_USE_GATES WORKS_USE_POLICY_MD WORKS_USE_THICKNESS \
  WORKS_USE_WAIT_SECONDS WORKS_USE_UNATTENDED WORKS_USE_ALLOW_DELETE WORKS_USE_ALLOW_STOPPED WORKS_USE_FINAL_GATE \
  WORKS_DOGFOOD_TDD_SUITE WORKS_DOGFOOD_FINAL_GATE WORKS_DESIGN_ONLY \
  WORKS_KEYCHAIN_ITEM WORKS_AUTH_FROM WORKS_ANSWER_CMD WORKS_ANSWER_WHO WORKS_RUN_ID WORKS_RUN_ROW \
  WORKS_REAL_CLAUDE WORKS_ADAPTER WORKS_ADAPTER_HOME WORKS_ARCHON_VERSION WORKS_CLAUDE_VERSION \
  WORKS_GH WORKS_GH_ACTIVE WORKS_REAL_GH CONTEXT7_API_KEY CLAUDE_BIN_PATH ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN \
  ARTIFACTS_DIR WORKFLOW_ID; do
  unset "$_works_env"
done
# ラインの節（tdd-suite.sh）から起こすと Archon が INPUTS_* を渡す。script_io は INPUTS_BASE_REV などを env から読むので、
# 自分で置かない試験が run の値を拾う。名は節ごとに違うので接頭辞で落とす
for _works_env in $(env | sed -n 's/^\(INPUTS_[A-Za-z0-9_]*\)=.*/\1/p'); do
  unset "$_works_env"
done
unset _works_env
