#!/usr/bin/env bash
# Colab VM：安装固定 revision 的 ComfyUI 与 comfyui-SelfLift、H3 运行依赖，并把 Drive 中的权重
# 缓存到本地盘、按 Windows 节点相同的文件名链接进 ComfyUI models。可重复执行。
# 权重唯一来源是已挂载的 Drive（只读取、不删除）；本地盘缓存随 VM 回收。
set -euo pipefail

COMFY_REV=a7169322485d0049380fb207fa17e9fb3ec40486
SELFLIFT_REV=835c3cf7919410f71f414688f049c6ca497789d0
COMFY=/content/ComfyUI
DRIVE=${SLATEHAND_COLAB_MODEL_DRIVE:-/content/drive/MyDrive/model/minimax-h3}
CACHE=/content/models
STAGE=/content/dl

[ -d "$DRIVE" ] || { echo "Drive 未挂载或缺少 ${DRIVE}；先在本机运行 colab drivemount。" >&2; exit 2; }

if [ ! -d "$COMFY/.git" ]; then
  git clone -q https://github.com/comfyanonymous/ComfyUI.git "$COMFY"
fi
git -C "$COMFY" checkout -q "$COMFY_REV"
SELFLIFT="$COMFY/custom_nodes/comfyui-SelfLift"
if [ ! -d "$SELFLIFT/.git" ]; then
  git clone -q https://github.com/facok/comfyui-SelfLift.git "$SELFLIFT"
fi
git -C "$SELFLIFT" checkout -q "$SELFLIFT_REV"

if ! python3 -c "import sageattention, comfy_aimdo" 2>/dev/null; then
  # 保留 Colab 自带的 CUDA 版 torch，不让 ComfyUI requirements 替换。
  grep -v -E '^(torch|torchvision|torchaudio)([<>=~ ]|$)' "$COMFY/requirements.txt" > /tmp/comfy-req.txt
  pip install -q -r /tmp/comfy-req.txt
  if [ -f "$SELFLIFT/requirements.txt" ]; then pip install -q -r "$SELFLIFT/requirements.txt"; fi
  pip install -q sageattention==1.0.6
fi

# 目标路径（相对 ComfyUI/models）= Drive 中的源文件名 : 字节数
MODELS=(
  "diffusion_models/minimax-h3/DasiwaMinimaxH3_dasiwaHybridV2_int8.safetensors=dasiwa_minimax_h3_ref2va_v2_pruned_hybrid_int8_row-wise_convrot_runtime_mixed.safetensors:20967669160"
  "diffusion_models/minimax-h3/DasiwaMinimaxH3_dasiwaHybridTurboV2_int8.safetensors=dasiwa_minimax_h3_ref2va_v2_pruned_hybrid_turbo_int8_row-wise_convrot_runtime_mixed.safetensors:20967669168"
  "text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors=qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors:15687142551"
  "vae/minimax-h3/minimax_h3_video_vae_fp16.safetensors=minimax_h3_video_vae_fp16.safetensors:5207808496"
  "vae/minimax-h3/minimax_h3_audio_vae_fp32.safetensors=minimax_h3_audio_vae_fp32.safetensors:605254808"
  "latent_upscale_models/minimax_h3_latent_upscaler_3d_conv_v1_fp16.safetensors=minimax_h3_latent_upscaler_3d_conv_v1_fp16.safetensors:690592672"
  # 可选：官方 Pruned BF16（「官方 Pruned BF16 · 20 步」预设），Drive 里没有时跳过。
  "?diffusion_models/minimax-h3/minimax_h3_fl2va_pruned_bf16.safetensors=minimax_h3_fl2va_pruned_bf16.safetensors:40225724176"
  "?diffusion_models/minimax-h3/minimax_h3_ref2va_pruned_bf16.safetensors=minimax_h3_ref2va_pruned_bf16.safetensors:40225724176"
)

mkdir -p "$CACHE"
for entry in "${MODELS[@]}"; do
  optional=0
  if [ "${entry:0:1}" = "?" ]; then optional=1; entry=${entry:1}; fi
  target=${entry%%=*}
  rest=${entry#*=}
  source=${rest%%:*}
  size=${rest##*:}
  cached="$CACHE/$source"
  if [ ! -f "$cached" ] || [ "$(stat -c %s "$cached")" != "$size" ]; then
    if [ -f "$STAGE/$source" ] && [ "$(stat -c %s "$STAGE/$source")" = "$size" ]; then
      ln -f "$STAGE/$source" "$cached"
    else
      if [ ! -f "$DRIVE/$source" ]; then
        if [ "$optional" = 1 ]; then echo "跳过可选权重：$source"; continue; fi
        echo "Drive 缺少权重：$source" >&2; exit 3
      fi
      echo "从 Drive 缓存 $source ……"
      cp "$DRIVE/$source" "$cached.part"
      mv "$cached.part" "$cached"
    fi
    [ "$(stat -c %s "$cached")" = "$size" ] || { echo "权重大小不符：$source" >&2; exit 3; }
  fi
  mkdir -p "$(dirname "$COMFY/models/$target")"
  ln -sfn "$cached" "$COMFY/models/$target"
done

python3 -c "import torch, sageattention, comfy_aimdo; assert torch.cuda.is_available(); print('H3 Colab 环境就绪：', torch.__version__, torch.cuda.get_device_name(0))"
