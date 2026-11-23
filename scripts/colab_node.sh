#!/usr/bin/env bash
# 手动开关 Colab G4 模型节点。权重从 Hugging Face 多连接下载，不需要 Google Drive。
#
#   scripts/colab_node.sh up       开机（缺会话时创建 G4）→ 同步代码与 Token → 安装环境、下载 Turbo 权重 →
#                            启动模型服务 → 进入状态面板。代码未变化且服务在运行时跳过部署与重启。
#                            可重复执行，已完成的步骤会跳过。
#   scripts/colab_node.sh status   打印一次状态面板（服务、GPU、权重、任务、后台下载、Core 隧道）
#   scripts/colab_node.sh watch    持续刷新状态面板（up 结束后自动进入；Ctrl-C 只退出查看）
#   scripts/colab_node.sh down     回收 VM（VM 本地环境与权重缓存清空；下次 up 重建）
#
# Core 运行时会自动经 colab ssh 建立隧道；在 Provider 设置页把相应插件的「运行节点」切到
# Colab G4 即可使用。会话名取本仓库 provider.local.env 的 SLATEHAND_COLAB_SESSION。
set -euo pipefail
trap 'echo "colab_node.sh 第 ${LINENO} 行失败（退出码 $?），已中止。" >&2' ERR

REPO=$(cd "$(dirname "$0")/.." && pwd)
cd "$REPO"
TOKEN=var/secrets/colab-model-service-token
HF_TOKEN_FILE=var/secrets/colab-huggingface-token
SESSION=${SLATEHAND_COLAB_SESSION:-$(sed -n 's/^SLATEHAND_COLAB_SESSION=//p' provider.local.env 2>/dev/null | tr -d "'\"" | tail -n 1)}
SESSION=${SESSION:-slate}
COLAB=${SLATEHAND_COLAB_CLI:-colab}
REMOTE=/content/slatehand-providers

# 远程命令走 kernel 通道（colab exec），不占用 SSH：Core 运行时其 Colab 隧道独占唯一的 colab ssh 连接。
# colab exec 不传递远端进程的退出码。用远端标记区分执行失败（1）与未收到结果（2），输出实时回显。
remote() (
  local result status detail
  result=$(mktemp -d -t slatehand-remote) || return 1
  trap 'rm -rf "$result"' EXIT
  if {
    printf 'command = %s\n' "$(printf '%s' "$1" | python3 -c 'import sys; print(repr(sys.stdin.read()))')"
    cat <<'PY'
import subprocess, sys
process = subprocess.Popen(["bash", "-lc", command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
for chunk in iter(lambda: process.stdout.read1(65536), b""):
    sys.stdout.write(chunk.decode(errors="replace"))
    sys.stdout.flush()
print(f"__SLATEHAND_RC__={process.wait()}")
PY
  } | "$COLAB" exec -s "$SESSION" --timeout "${2:-0}" 2>"$result/stderr" \
    | tee "$result/stdout" | { grep -v '^__SLATEHAND_RC__=' || true; } \
    | python3 "$REPO/scripts/progress_view.py"; then :; fi
  status=$(sed -n 's/^__SLATEHAND_RC__=//p' "$result/stdout" | tail -n 1)
  if [ -z "$status" ]; then
    detail=$(tail -n 1 "$result/stderr")
    echo "Colab 会话 ${SESSION} 未返回命令结果${detail:+（${detail}）}。" >&2
    return 2
  fi
  [ "$status" = 0 ]
)

# 只重试可重复执行的命令。远端明确报错时保留失败，由调用方处理。
remote_retry() {
  local attempt status
  for attempt in 1 2 3; do
    if remote "$1" 45; then return 0; else status=$?; fi
    if [ "$status" -ne 2 ] || [ "$attempt" -eq 3 ]; then return "$status"; fi
    echo "将在 2 秒后重新连接 Colab（重试 ${attempt}/2）。" >&2
    sleep 2
  done
}
# 更新部署前停止旧安装器的进程组，保留已完成的权重和正在执行的模型任务。
stop_background_setup() {
  remote_retry "set -e
    pid=\$(cat /content/slatehand-state/setup-background.pid 2>/dev/null || true)
    case \"\$pid\" in ''|*[!0-9]*) exit 0 ;; esac
    command=\$(ps -p \"\$pid\" -o args= 2>/dev/null || true)
    group=\$(ps -p \"\$pid\" -o pgid= 2>/dev/null | tr -d ' ' || true)
    case \"\$command\" in
      *' $1 --background') ;;
      *) exit 0 ;;
    esac
    [ \"\$group\" = \"\$pid\" ] || exit 1
    kill -TERM -- \"-\$pid\" 2>/dev/null || true
    for attempt in \$(seq 1 20); do
      if ! kill -0 -- \"-\$pid\" 2>/dev/null; then exit 0; fi
      sleep 1
    done
    echo '等待旧后台安装退出超时。' >&2
    exit 1"
}

session_running() { "$COLAB" sessions 2>/dev/null | grep -q "^\[$SESSION\] "; }

# 状态面板的行：远端服务、GPU、权重、任务与后台下载，加上本机到 Colab 的隧道（Core 经它提交）。
panel_rows() {
  local remote_rows
  if remote_rows=$(remote "python3 $REMOTE/default_model_providers_implement/colab/node_status.py" 15 2>/dev/null) \
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
      local archive digest status deployed server setup
      deployed=$REMOTE/.deployed-sha256
      server=$REMOTE/default_model_providers_implement/colab/run_server.sh
      setup=$REMOTE/default_model_providers_implement/colab/setup.sh
      if [ ! -s "$TOKEN" ]; then
        mkdir -p "$(dirname "$TOKEN")"
        (umask 077 && openssl rand -hex 32 > "$TOKEN")
        echo "已生成 ${TOKEN}。"
      fi
      if ! session_running; then
        python3 "$REPO/scripts/colab_allocate.py" "$COLAB" "$SESSION" || exit "$?"
      fi
      echo "==> 同步代码与 Token"
      if [ -s "$HF_TOKEN_FILE" ]; then
        remote_retry "umask 077; touch /root/.slatehand-colab-hf-token && chmod 600 /root/.slatehand-colab-hf-token"
        "$COLAB" upload -s "$SESSION" "$HF_TOKEN_FILE" /root/.slatehand-colab-hf-token >/dev/null
        remote_retry "chmod 600 /root/.slatehand-colab-hf-token"
      fi
      archive=$(mktemp -t slatehand-colab)
      trap "$(printf 'rm -f %q' "$archive")" EXIT
      # gzip -n 不写时间戳：代码不变则包的哈希不变，可判断是否需要重新部署。
      COPYFILE_DISABLE=1 tar --no-xattrs --exclude '__pycache__' -cf - default_model_providers_implement | gzip -n > "$archive"
      digest=$(shasum -a 256 "$archive" | cut -d' ' -f1)
      if remote_retry "[ \"\$(cat $deployed 2>/dev/null)\" = $digest ] && bash $server status >/dev/null" >/dev/null; then
        echo "代码未变化且模型服务运行中，跳过部署与重启（不打断运行中的任务）。"
        remote_retry "bash $setup --ensure-background"
      else
        status=$?
        if [ "$status" -ne 1 ]; then return "$status"; fi
        "$COLAB" upload -s "$SESSION" "$archive" /content/slatehand-providers.tar.gz >/dev/null
        "$COLAB" upload -s "$SESSION" "$TOKEN" /root/.slatehand-colab-token >/dev/null
        stop_background_setup "$setup"
        remote "chmod 600 /root/.slatehand-colab-token && rm -rf $REMOTE/default_model_providers_implement && mkdir -p $REMOTE && tar -xzf /content/slatehand-providers.tar.gz -C $REMOTE"
        echo "==> 安装环境、下载 Turbo 所需权重（其余权重随后在后台下载）"
        # 先完成旧服务的停止，再重试可重复执行的 start，避免启动成功后丢回执导致再停一次。
        remote "set -e
          SLATEHAND_PROGRESS_INTERVAL=3 bash $setup
          if bash $server status >/dev/null; then
            bash $server stop >/dev/null
            for attempt in \$(seq 1 30); do
              if ! bash $server status >/dev/null; then exit 0; fi
              sleep 1
            done
            echo '等待旧模型服务退出超时。' >&2
            exit 1
          fi"
        echo "==> 启动模型服务"
        remote_retry "bash $server start && echo $digest > $deployed"
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
