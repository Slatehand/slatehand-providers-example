#!/usr/bin/env bash
# Colab VM 安装，分两段，可重复执行（已完成的步骤跳过）：
#   setup.sh               前台：安装固定 revision 的 ComfyUI 与 comfyui-SelfLift、H3 依赖，只缓存 Turbo V2
#                          及其共用权重（文本编码器、VAE、SelfLift 放大器），随后在后台拉起 --background 并返回，
#                          调用方即可启动服务。
#   setup.sh --background  后台：Breeze TTS 2（固定上游 revision、独立 Python 3.12 venv、模型），再依次缓存
#                          DaSiWa Hybrid V2 与官方 Pruned BF16。
# 权重从已挂载的 Drive 复制到本地盘（只读取与新增、不删除），完整复制并核对大小后才链接进 ComfyUI models，
# 服务不会读到半截文件；尚未搬完的模型被调用时任务直接失败并提示稍后重试。本地盘缓存随 VM 回收。
set -euo pipefail

COMFY_REV=a7169322485d0049380fb207fa17e9fb3ec40486
SELFLIFT_REV=835c3cf7919410f71f414688f049c6ca497789d0
COMFY=/content/ComfyUI
DRIVE=${SLATEHAND_COLAB_MODEL_DRIVE:-/content/drive/MyDrive/model/minimax-h3}
CACHE=/content/models
STAGE=/content/dl
STATE=/content/slatehand-state
BACKGROUND_PID=$STATE/setup-background.pid
BACKGROUND_LOG=$STATE/setup-background.log

[ -d "$DRIVE" ] || { echo "Drive 未挂载或缺少 ${DRIVE}；先用本机 scripts/colab_node.sh up 挂载。" >&2; exit 2; }
mkdir -p "$CACHE" "$STATE"

COPY="python3 $(cd "$(dirname "$0")" && pwd)/copy_progress.py"

# 每项「ComfyUI models 下的目标路径|Drive 源文件名|字节数|optional」。
# needs_copy：本地缓存与 /content/dl 暂存都没有完整文件，且 Drive 有源文件（缺失的必需文件由 stage 报错）。
needs_copy() {
  local source=$1 size=$2
  [ -f "$CACHE/$source" ] && [ "$(stat -c %s "$CACHE/$source")" = "$size" ] && return 1
  [ -f "$STAGE/$source" ] && [ "$(stat -c %s "$STAGE/$source")" = "$size" ] && return 1
  [ -f "$DRIVE/$source" ]
}

# stage_all <阶段名> <项>...：先算出本阶段要从 Drive 复制的总量，再逐个复制并共用一条总进度。
stage_all() {
  local label=$1; shift
  local total=0 done=0 entry target source size optional rest
  for entry in "$@"; do
    IFS='|' read -r target source size optional <<< "$entry"
    if needs_copy "$source" "$size"; then total=$((total + size)); fi
  done
  [ "$total" -gt 0 ] && echo "$(date +%T) ${label}：需从 Drive 复制 $(awk "BEGIN{printf \"%.1f\", $total/1073741824}") GB"
  for entry in "$@"; do
    IFS='|' read -r target source size optional <<< "$entry"
    local cached="$CACHE/$source"
    if [ ! -f "$cached" ] || [ "$(stat -c %s "$cached")" != "$size" ]; then
      if [ -f "$STAGE/$source" ] && [ "$(stat -c %s "$STAGE/$source")" = "$size" ]; then
        ln -f "$STAGE/$source" "$cached"
      elif [ -f "$DRIVE/$source" ]; then
        $COPY "$DRIVE/$source" "$cached.part" --label "$label" --done "$done" --total "$total"
        mv "$cached.part" "$cached"
        done=$((done + size))
      elif [ -n "$optional" ]; then
        echo "跳过可选权重：${source}"; continue
      else
        echo "Drive 缺少权重：${source}" >&2; return 3
      fi
      [ "$(stat -c %s "$cached")" = "$size" ] || { echo "权重大小不符：${source}" >&2; return 3; }
    fi
    mkdir -p "$(dirname "$COMFY/models/$target")"
    ln -sfn "$cached" "$COMFY/models/$target"
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
  stage_all "Turbo 前台缓存" \
    "$H3/DasiwaMinimaxH3_dasiwaHybridTurboV2_int8.safetensors|dasiwa_minimax_h3_ref2va_v2_pruned_hybrid_turbo_int8_row-wise_convrot_runtime_mixed.safetensors|20967669168|" \
    "text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors|qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors|15687142551|" \
    "vae/minimax-h3/minimax_h3_video_vae_fp16.safetensors|minimax_h3_video_vae_fp16.safetensors|5207808496|" \
    "vae/minimax-h3/minimax_h3_audio_vae_fp32.safetensors|minimax_h3_audio_vae_fp32.safetensors|605254808|" \
    "latent_upscale_models/minimax_h3_latent_upscaler_3d_conv_v1_fp16.safetensors|minimax_h3_latent_upscaler_3d_conv_v1_fp16.safetensors|690592672|"
  python3 -c "import torch, sageattention, comfy_aimdo; assert torch.cuda.is_available(); print('H3 Turbo 就绪：', torch.__version__, torch.cuda.get_device_name(0))"

  if [ -f "$BACKGROUND_PID" ] && kill -0 "$(cat "$BACKGROUND_PID")" 2>/dev/null; then
    echo "后台搬运已在进行（日志 ${BACKGROUND_LOG}）。"
  else
    setsid nohup bash "$0" --background >> "$BACKGROUND_LOG" 2>&1 &
    echo $! > "$BACKGROUND_PID"
    echo "后台开始搬运 Breeze、Hybrid V2 与官方 Pruned BF16（日志 ${BACKGROUND_LOG}）。"
  fi
}

BREEZE_REV=008f769016b0a24711becd7a4925030bc93f608c
BREEZE_MODEL_REV=3e28c5151381a722f1d8661b4118c298caa77aa4
BREEZE=/content/breeze-tts
BREEZE_VENV=/content/breeze-venv
BREEZE_DRIVE=${SLATEHAND_COLAB_BREEZE_DRIVE:-/content/drive/MyDrive/model/breeze-tts-2}
BREEZE_MODEL=$CACHE/Breeze-TTS-2

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
    if [ -f "$BREEZE_DRIVE/model.safetensors.index.json" ]; then
      $COPY "$BREEZE_DRIVE" "$BREEZE_MODEL.part" --label "Breeze 模型缓存"
    else
      echo "$(date +%T) 首次下载 Breeze-TTS-2（Hugging Face 固定 revision）并存入 Drive ……"
      uv pip install -q --python "$BREEZE_VENV/bin/python" huggingface_hub
      "$BREEZE_VENV/bin/python" -c "from huggingface_hub import snapshot_download; snapshot_download('BreezeBlue/Breeze-TTS-2', revision='$BREEZE_MODEL_REV', local_dir='$BREEZE_MODEL.part')"
      rm -rf "$BREEZE_MODEL.part/.cache"
      mkdir -p "$BREEZE_DRIVE"
      cp -r "$BREEZE_MODEL.part/." "$BREEZE_DRIVE/"
    fi
    mv "$BREEZE_MODEL.part" "$BREEZE_MODEL"
  fi
  "$BREEZE_VENV/bin/python" -c "import torch; assert torch.cuda.is_available(); print('Breeze 就绪：', torch.__version__, torch.cuda.get_device_capability(0))"
}

background() {
  echo "$(date +%T) ===== 后台搬运开始"
  # 独立进程运行，set -e 在其中生效；失败不影响后续 H3 权重。
  bash "$0" --breeze || echo "$(date +%T) Breeze 安装失败，继续搬运 H3 权重。"
  stage_all "Hybrid V2 后台缓存" \
    "$H3/DasiwaMinimaxH3_dasiwaHybridV2_int8.safetensors|dasiwa_minimax_h3_ref2va_v2_pruned_hybrid_int8_row-wise_convrot_runtime_mixed.safetensors|20967669160|"
  echo "$(date +%T) Hybrid V2 就绪。"
  stage_all "官方 BF16 后台缓存" \
    "$H3/minimax_h3_fl2va_pruned_bf16.safetensors|minimax_h3_fl2va_pruned_bf16.safetensors|40225724176|optional" \
    "$H3/minimax_h3_ref2va_pruned_bf16.safetensors|minimax_h3_ref2va_pruned_bf16.safetensors|40225724176|optional"
  echo "$(date +%T) ===== 后台搬运完成"
}

case "${1:-}" in
  "") foreground ;;
  --background) background ;;
  --breeze) breeze ;;
  *) echo "用法：$0 [--background]" >&2; exit 2 ;;
esac
