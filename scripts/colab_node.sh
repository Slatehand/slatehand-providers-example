#!/usr/bin/env bash
# 手动开关 Colab G4 节点（H3 + Breeze TTS 2）。权重从 Hugging Face 多连接下载，不需要 Google Drive。
#
#   scripts/colab_node.sh up       开机（缺会话时创建 G4）→ 同步代码与 Token → 安装环境、下载 Turbo 权重 →
#                            启动模型服务 → 进入状态面板。代码未变化且服务在运行时跳过部署与重启。
#                            可重复执行，已完成的步骤会跳过。
#   scripts/colab_node.sh status   打印一次状态面板（服务、GPU、权重、任务、后台下载、Core 隧道）
#   scripts/colab_node.sh watch    持续刷新状态面板（up 结束后自动进入；Ctrl-C 只退出查看）
#   scripts/colab_node.sh down     回收 VM（VM 本地环境与权重缓存清空；下次 up 重建）
#
# Core 运行时会自动经 colab ssh 建立隧道；在 Provider 设置页把 H3 / Breeze 的「运行节点」切到
# Colab G4 即可使用。会话名取本仓库 provider.local.env 的 SLATEHAND_COLAB_SESSION。
set -euo pipefail
trap 'echo "colab_node.sh 第 ${LINENO} 行失败（退出码 $?），已中止。" >&2' ERR

REPO=$(cd "$(dirname "$0")/.." && pwd)
cd "$REPO"
TOKEN=var/secrets/colab-model-service-token
SESSION=${SLATEHAND_COLAB_SESSION:-$(sed -n 's/^SLATEHAND_COLAB_SESSION=//p' provider.local.env 2>/dev/null | tr -d "'\"" | tail -n 1)}
SESSION=${SESSION:-slate}
COLAB=${SLATEHAND_COLAB_CLI:-colab}
REMOTE=/content/slatehand-providers

# 远程命令走 kernel 通道（colab exec），不占用 SSH：Core 运行时其 Colab 隧道独占唯一的 colab ssh 连接。
# colab exec 的退出码恒为 0，这里由远端打印退出码标记，本机解析后作为返回值；输出实时回显。
remote() {
  local output status
  output=$(mktemp -t slatehand-remote)
  {
    printf 'command = %s\n' "$(printf '%s' "$1" | python3 -c 'import sys; print(repr(sys.stdin.read()))')"
    cat <<'PY'
import subprocess, sys
process = subprocess.Popen(["bash", "-lc", command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
for chunk in iter(lambda: process.stdout.read1(65536), b""):
    sys.stdout.write(chunk.decode(errors="replace"))
    sys.stdout.flush()
print(f"__SLATEHAND_RC__={process.wait()}")
PY
  } | "$COLAB" exec -s "$SESSION" --timeout 0 | tee "$output" | { grep -v '^__SLATEHAND_RC__=' || true; } \
    | python3 "$REPO/scripts/progress_view.py"
  status=$(sed -n 's/^__SLATEHAND_RC__=//p' "$output" | tail -n 1)
  rm -f "$output"
  [ "${status:-1}" = 0 ]
}
session_running() { "$COLAB" sessions 2>/dev/null | grep -q "^\[$SESSION\] "; }

# 状态面板的行：远端服务、GPU、权重、任务与后台下载，加上本机到 Colab 的隧道（Core 经它提交）。
panel_rows() {
  local remote_rows
  if remote_rows=$(remote "python3 $REMOTE/default_model_providers_implement/colab/node_status.py" 2>/dev/null) \
    && [ -n "$remote_rows" ]; then
    printf '%s\n' "$remote_rows"
  else
    printf '会话\t无法连接（VM 可能已回收；用 %s up 重新开机）\n' "$0"
  fi
  local port=${SLATEHAND_COLAB_LOCAL_PORT:-18791}
  if [ "$(curl -s -o /dev/null -w '%{http_code}' -m 3 "http://127.0.0.1:${port}/" || true)" = 401 ]; then
    printf 'Core 连接\t隧道已连通（127.0.0.1:%s → Colab）\n' "$port"
  else
    printf 'Core 连接\t隧道未连通（Core 未运行，或会话刚开、隧道尚未建立）\n'
  fi
}

# 主体包在函数里，并在最后一行“调用 + 退出”：bash 先读完整个文件与这一行再执行、执行完直接退出，
# 运行中修改脚本也不会读错位。
main() {
  case "${1:-}" in
    up)
      if [ ! -s "$TOKEN" ]; then
        mkdir -p "$(dirname "$TOKEN")"
        (umask 077 && openssl rand -hex 32 > "$TOKEN")
        echo "已生成 ${TOKEN}。"
      fi
      if ! session_running; then
        echo "==> 创建 Colab G4 会话 ${SESSION}"
        "$COLAB" new -s "$SESSION" --gpu G4
      fi
      echo "==> 同步代码与 Token"
      archive=$(mktemp -t slatehand-colab).tar.gz
      trap 'rm -f "$archive"' EXIT
      # gzip -n 不写时间戳：代码不变则包的哈希不变，可判断是否需要重新部署。
      COPYFILE_DISABLE=1 tar --no-xattrs --exclude '__pycache__' -cf - default_model_providers_implement | gzip -n > "$archive"
      digest=$(shasum -a 256 "$archive" | cut -d' ' -f1)
      if remote "[ \"\$(cat $REMOTE/.deployed-sha256 2>/dev/null)\" = $digest ] && bash $REMOTE/default_model_providers_implement/colab/run_server.sh status >/dev/null" >/dev/null 2>&1; then
        echo "代码未变化且模型服务运行中，跳过部署与重启（不打断运行中的任务）。"
      else
        "$COLAB" upload -s "$SESSION" "$archive" /content/slatehand-providers.tar.gz >/dev/null
        "$COLAB" upload -s "$SESSION" "$TOKEN" /root/.slatehand-colab-token >/dev/null
        remote "chmod 600 /root/.slatehand-colab-token && rm -rf $REMOTE/default_model_providers_implement && mkdir -p $REMOTE && tar -xzf /content/slatehand-providers.tar.gz -C $REMOTE"
        echo "==> 安装环境、下载 Turbo 所需权重（其余权重随后在后台下载）"
        remote "SLATEHAND_PROGRESS_INTERVAL=3 bash $REMOTE/default_model_providers_implement/colab/setup.sh"
        echo "==> 启动模型服务"
        remote "bash $REMOTE/default_model_providers_implement/colab/run_server.sh stop >/dev/null; bash $REMOTE/default_model_providers_implement/colab/run_server.sh start && echo $digest > $REMOTE/.deployed-sha256"
      fi
      echo "==> 进入状态面板（不用时记得 $0 down，空闲也按约每小时 10 个计算单元计费）"
      sleep 2
      main watch
      ;;
    status)
      panel_rows | python3 "$REPO/scripts/progress_view.py" --panel "Colab 节点 ${SESSION}" | cat
      ;;
    watch)
      while true; do
        panel_rows | python3 "$REPO/scripts/progress_view.py" --panel "Colab 节点 ${SESSION}"
        sleep 5
      done
      ;;
    down)
      if session_running; then
        "$COLAB" stop -s "$SESSION"
      else
        echo "会话 ${SESSION} 未运行。"
      fi
      ;;
    *)
      echo "用法：$0 up|status|watch|down" >&2
      exit 2
      ;;
  esac
}

main "$@"; exit $?
