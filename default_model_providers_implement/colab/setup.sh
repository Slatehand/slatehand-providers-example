#!/usr/bin/env bash
# Colab VM 安装。前台准备 H3 Turbo 和共用权重，随即可启动服务。
# 后台先准备其它能力，最后才下载 H3 Hybrid V2 与官方 Pruned BF16。
# 权重全部来自固定 commit 的 Hugging Face 仓库（DaSiWa 用与 Civitai 发布 SHA256 一致的转存），由
# fetch_progress.py 多连接分块下载到本地盘，完整下载并核对大小后才链接进 ComfyUI models，服务不会读到半截
# 文件；尚未下载完的模型被调用时任务直接失败并提示稍后重试。不需要 Google Drive。本地盘缓存随 VM 回收。
set -euo pipefail

COMFY_REV=a7169322485d0049380fb207fa17e9fb3ec40486
SELFLIFT_REV=835c3cf7919410f71f414688f049c6ca497789d0
COMFY=/content/ComfyUI
CACHE=/content/models
STATE=/content/slatehand-state
BACKGROUND_PID=$STATE/setup-background.pid
BACKGROUND_LOG=$STATE/setup-background.log
READY=$STATE/model-ready
COLAB_DIR=$(cd "$(dirname "$0")" && pwd)
SETUP_VERSION=$(sha256sum "$0" "$COLAB_DIR/setup_models.sh" | sha256sum | cut -d' ' -f1)
# shellcheck source=setup_models.sh
source "$COLAB_DIR/setup_models.sh"
mkdir -p "$CACHE" "$READY"

FETCH=$COLAB_DIR/fetch_progress.py
HF=https://huggingface.co
COMFY_ORG=$HF/Comfy-Org/MiniMax-H3/resolve/54472221d27c695fca9621b0c3ed52f06c4af707
UPSCALER=$HF/LBH-123-AI/Minimax_h3_latent_Upscaler/resolve/3f941d5d182014dd5c0a5e16330420ee2d4aa0c6/minimax_h3_latent_upscaler_3d_conv_v1
# kogehek 的转存与 Civitai DaSiWa Hybrid V2 / Turbo V2 int8 的 SHA256 一致（LFS 按内容寻址）。
DASIWA=$HF/kogehek/DaSiWa_MiniMax_H3/resolve/f17b8f8190e172f437fe84b8854b33057f5e9bc0

complete() { [ -f "$1" ] && [ "$(stat -c %s "$1")" = "$2" ]; }

# stage_all <阶段名> <项>...，每项「本地缓存文件|URL|字节数|ComfyUI models 下的链接路径（可空）」：
# 先算出本阶段要下载的总量，再逐个下载（共用一条总进度），完整后才建立链接。
stage_all() {
  local label=$1; shift
  local total=0 done=0 entry cached url size link available
  for entry in "$@"; do
    IFS='|' read -r cached url size link <<< "$entry"
    if ! complete "$cached" "$size"; then
      rm -f "$cached.part"
      total=$((total + size))
    fi
  done
  if [ "$total" -gt 0 ]; then
    available=$(df -PB1 "$CACHE" | awk 'NR == 2 {print $4}')
    if [ "$available" -lt "$total" ]; then
      echo "$(date +%T) ${label}：可用空间不足（剩余 ${available} 字节，需 ${total} 字节）。" >&2
      return 1
    fi
    echo "$(date +%T) ${label}：需下载 $(awk "BEGIN{printf \"%.1f\", $total/1073741824}") GB"
  fi
  for entry in "$@"; do
    IFS='|' read -r cached url size link <<< "$entry"
    if ! complete "$cached" "$size"; then
      mkdir -p "$(dirname "$cached")"
      if [ "$size" -lt 67108864 ]; then
        curl --fail --silent --show-error --location --retry 3 -o "$cached.part" "$url"
      else
        python3 "$FETCH" "$url" "$cached.part" --size "$size" --label "$label" --done "$done" --total "$total"
      fi
      if ! complete "$cached.part" "$size"; then
        echo "${label}：${cached##*/} 下载大小不符。" >&2
        rm -f "$cached.part"
        return 1
      fi
      mv "$cached.part" "$cached"
      done=$((done + size))
    fi
    if [ -n "$link" ]; then
      mkdir -p "$(dirname "$COMFY/models/$link")"
      ln -sfn "$cached" "$COMFY/models/$link"
    fi
  done
}

H3=diffusion_models/minimax-h3

foreground() {
  if [ ! -d "$COMFY/.git" ]; then
    git clone -q https://github.com/comfyanonymous/ComfyUI.git "$COMFY"
  fi
  git -C "$COMFY" checkout -q "$COMFY_REV"
  local selflift="$COMFY/custom_nodes/comfyui-SelfLift"
  if [ ! -d "$selflift/.git" ]; then
    git clone -q https://github.com/facok/comfyui-SelfLift.git "$selflift"
  fi
  git -C "$selflift" checkout -q "$SELFLIFT_REV"
  if ! python3 -c "import sageattention, comfy_aimdo" 2>/dev/null; then
    # 保留 Colab 自带的 CUDA 版 torch，不让 ComfyUI requirements 替换。
    grep -v -E '^(torch|torchvision|torchaudio)([<>=~ ]|$)' "$COMFY/requirements.txt" > /tmp/comfy-req.txt
    pip install -q -r /tmp/comfy-req.txt
    if [ -f "$selflift/requirements.txt" ]; then pip install -q -r "$selflift/requirements.txt"; fi
    pip install -q sageattention==1.0.6
  fi

  # Turbo V2 · 8 步所需的全部权重。
  stage_all "Turbo 前台下载" \
    "$CACHE/DasiwaMinimaxH3_dasiwaHybridTurboV2_int8.safetensors|$DASIWA/DasiwaMinimaxH3_dasiwaHybridTurboV2_int8.safetensors|20967669168|$H3/DasiwaMinimaxH3_dasiwaHybridTurboV2_int8.safetensors" \
    "$CACHE/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors|$COMFY_ORG/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors|15687142551|text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors" \
    "$CACHE/minimax_h3_video_vae_fp16.safetensors|$COMFY_ORG/vae/minimax_h3_video_vae_fp16.safetensors|5207808496|vae/minimax-h3/minimax_h3_video_vae_fp16.safetensors" \
    "$CACHE/minimax_h3_audio_vae_fp32.safetensors|$COMFY_ORG/vae/minimax_h3_audio_vae_fp32.safetensors|605254808|vae/minimax-h3/minimax_h3_audio_vae_fp32.safetensors" \
    "$CACHE/minimax_h3_latent_upscaler_3d_conv_v1_fp16.safetensors|$UPSCALER/minimax_h3_latent_upscaler_3d_conv_v1_fp16.safetensors|690592672|latent_upscale_models/minimax_h3_latent_upscaler_3d_conv_v1_fp16.safetensors"
  python3 -c "import torch, sageattention, comfy_aimdo; assert torch.cuda.is_available(); print('H3 Turbo 就绪：', torch.__version__, torch.cuda.get_device_name(0))"

  ensure_background
}

ensure_background() {
  if [ "$(cat "$READY/background" 2>/dev/null || true)" = "$SETUP_VERSION" ]; then
    return
  fi
  if [ -f "$BACKGROUND_PID" ] && kill -0 "$(cat "$BACKGROUND_PID")" 2>/dev/null; then
    echo "后台下载已在进行（日志 ${BACKGROUND_LOG}）。"
    return
  fi
  setsid nohup bash "$0" --background </dev/null >> "$BACKGROUND_LOG" 2>&1 &
  echo "后台准备其余能力，最后下载 H3 可选权重（日志 ${BACKGROUND_LOG}）。"
}

BREEZE_REV=008f769016b0a24711becd7a4925030bc93f608c
BREEZE=/content/breeze-tts
BREEZE_VENV=/content/breeze-venv
BREEZE_MODEL=$CACHE/Breeze-TTS-2
BREEZE_HF=$HF/BreezeBlue/Breeze-TTS-2/resolve/3e28c5151381a722f1d8661b4118c298caa77aa4
# 固定 revision 的完整文件清单：相对路径|字节数。
BREEZE_FILES=(
  ".gitattributes|1570" "LICENSE|18719" "README.md|9818"
  "assets/breezeblue-logo.png|27533" "assets/tts-elo-leaderboard.svg|60367"
  "audio_tokenizer/config.json|2336" "audio_tokenizer/configuration.json|76"
  "audio_tokenizer/model.safetensors|682293092" "audio_tokenizer/preprocessor_config.json|234"
  "config.json|10161" "generation_config.json|251"
  "model-00001-of-00002.safetensors|4961989890" "model-00002-of-00002.safetensors|2004567152"
  "model.safetensors.index.json|109004" "special_tokens_map.json|886"
  "tokenizer.json|33386945" "tokenizer_config.json|1157960"
)

breeze() {
  if [ ! -d "$BREEZE/.git" ]; then
    git clone -q https://github.com/breezeblue-ai/breeze-tts.git "$BREEZE"
  fi
  git -C "$BREEZE" checkout -q "$BREEZE_REV"
  if ! "$BREEZE_VENV/bin/python" -c "import torch, qwen_tts, fastapi" 2>/dev/null; then
    command -v uv >/dev/null || pip install -q uv
    rm -rf "$BREEZE_VENV"  # VM 本地的旧 venv（不完整时重建）
    uv venv -q --python 3.12 "$BREEZE_VENV"
    uv pip install -q --python "$BREEZE_VENV/bin/python" -r "$BREEZE/requirements.txt"
  fi
  if [ ! -f "$BREEZE_MODEL/model.safetensors.index.json" ]; then
    # 先下载到 .part 目录，齐全后整体改名，Breeze 不会读到半套模型。
    local entries=() item
    for item in "${BREEZE_FILES[@]}"; do
      entries+=("$BREEZE_MODEL.part/${item%%|*}|$BREEZE_HF/${item%%|*}|${item##*|}|")
    done
    stage_all "Breeze 模型下载" "${entries[@]}"
    mv "$BREEZE_MODEL.part" "$BREEZE_MODEL"
  fi
  "$BREEZE_VENV/bin/python" -c "import torch; assert torch.cuda.is_available(); print('Breeze 就绪：', torch.__version__, torch.cuda.get_device_capability(0))"
}

prepare_stage() {
  local model=$1
  if [ "$(cat "$READY/$model" 2>/dev/null || true)" = "$SETUP_VERSION" ]; then return; fi
  echo "$(date +%T) 开始准备 ${model}。"
  rm -f "$READY/$model"
  if bash "$0" --stage "$model"; then
    echo "$SETUP_VERSION" > "$READY/$model"
    echo "$(date +%T) ${model} 就绪。"
  else
    echo "$(date +%T) ${model} 准备失败。" >&2
    return 1
  fi
}

background() {
  local model failed=()
  exec 9>"$STATE/setup-background.lock"
  flock -n 9 || return 0
  echo $$ > "$BACKGROUND_PID"
  trap 'rm -f "$BACKGROUND_PID"' EXIT
  rm -f "$READY/background"
  echo "$(date +%T) ===== 后台准备开始"
  command -v uv >/dev/null || python3 -m pip install -q uv
  for model in breeze qwen_image seedvr2 indextts2 yue2 demucs whisper hunyuan_foley stable_audio_3; do
    prepare_stage "$model" || failed+=("$model")
  done
  if [ "${#failed[@]}" -gt 0 ]; then
    echo "$(date +%T) 能力准备失败：${failed[*]}。H3 可选权重等基础能力就绪后再下载。" >&2
    return 1
  fi
  prepare_stage h3_hybrid
  prepare_stage h3_bf16
  echo "$SETUP_VERSION" > "$READY/background"
  echo "$(date +%T) ===== 后台下载完成"
}

h3_hybrid() {
  stage_all "Hybrid V2 后台下载" \
    "$CACHE/DasiwaMinimaxH3_dasiwaHybridV2_int8.safetensors|$DASIWA/DasiwaMinimaxH3_dasiwaHybridV2_int8.safetensors|20967669160|$H3/DasiwaMinimaxH3_dasiwaHybridV2_int8.safetensors"
}

h3_bf16() {
  stage_all "官方 BF16 后台下载" \
    "$CACHE/minimax_h3_fl2va_pruned_bf16.safetensors|$COMFY_ORG/diffusion_models/minimax_h3_fl2va_pruned_bf16.safetensors|40225724176|$H3/minimax_h3_fl2va_pruned_bf16.safetensors" \
    "$CACHE/minimax_h3_ref2va_pruned_bf16.safetensors|$COMFY_ORG/diffusion_models/minimax_h3_ref2va_pruned_bf16.safetensors|40225724176|$H3/minimax_h3_ref2va_pruned_bf16.safetensors"
}

case "${1:-}" in
  "") foreground ;;
  --background) background ;;
  --ensure-background) ensure_background ;;
  --stage)
    case "${2:-}" in
      breeze|qwen_image|seedvr2|indextts2|yue2|demucs|whisper|hunyuan_foley|stable_audio_3|h3_hybrid|h3_bf16)
        "$2" ;;
      *) echo "未知安装阶段。" >&2; exit 2 ;;
    esac
    ;;
  *) echo "用法：$0 [--background]" >&2; exit 2 ;;
esac
