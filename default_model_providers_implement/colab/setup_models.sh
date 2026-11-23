# 由 setup.sh 加载。各模型保留自己的 Python 环境，避免覆盖 ComfyUI 使用的 CUDA 版 torch。

checkout() {
  local url=$1 root=$2 revision=$3
  [ -d "$root/.git" ] || git clone -q "$url" "$root"
  git -C "$root" checkout -q "$revision"
}

cuda_env() {
  local root=$1 version=$2 torch=$3
  shift 3
  uv venv -q --allow-existing --python "$version" "$root"
  uv pip install -q --python "$root/bin/python" --index-url https://download.pytorch.org/whl/cu128 \
    "torch==$torch" "$@"
}

qwen_image() {
  local noctq=$HF/Noctaluna/Noct-Q-Uncensored-Qwen-Image-2.1/resolve/a81b9af51120a78e285e57906f2250a2a02080e9
  local qwen=$HF/Comfy-Org/Qwen-Image-2.1/resolve/aacf31a6d48e707f352ecba714cee0680da3479b
  stage_all "Qwen Image 下载" \
    "$CACHE/NoctQ_V4_int8_convrot.safetensors|$noctq/NoctQ_V4_int8_convrot.safetensors|7256784368|diffusion_models/qwen/NoctQ_V4_int8_convrot.safetensors" \
    "$CACHE/qwen3vl_8b_int8_convrot.safetensors|$qwen/text_encoders/qwen3vl_8b_int8_convrot.safetensors|9350798360|text_encoders/qwen/qwen3vl_8b_int8_convrot.safetensors" \
    "$CACHE/qwen_image_2.1_vae_bf16.safetensors|$qwen/vae/qwen_image_2.1_vae_bf16.safetensors|675509688|vae/qwen/qwen_image_2.1_vae_bf16.safetensors"
}

seedvr2() {
  local root=/content/seedvr2 model=$CACHE/SeedVR2
  local repo=$HF/numz/SeedVR2_comfyUI/resolve/09ced71023636e9bc8cdf9cdecfb2625d1e691e8
  checkout https://github.com/itontonpi/seedvr2.git "$root" 8cfe3390e09ad5faaad2555b78dcf9477db50dba
  cuda_env "$root/.venv" 3.12 2.10.0 torchvision==0.25.0
  uv pip install -q --python "$root/.venv/bin/python" -r "$root/requirements.txt"
  "$root/.venv/bin/python" "$root/inference_cli.py" --help >/dev/null
  stage_all "SeedVR2 下载" \
    "$model/seedvr2_ema_7b_sharp_fp8_e4m3fn.safetensors|$repo/seedvr2_ema_7b_sharp_fp8_e4m3fn.safetensors|8239729704|" \
    "$model/ema_vae_fp16.safetensors|$repo/ema_vae_fp16.safetensors|501324814|"
}

indextts2() {
  local root=/content/index-tts model=$CACHE/IndexTTS-2.5
  local repo=$HF/IndexTeam/IndexTTS-2.5/resolve/c39ce5ba981572cb187443877ff559dfb246ce63
  local w2v=$HF/facebook/w2v-bert-2.0/resolve/da985ba0987f70aaeb84a80f2851cfac8c697a7b
  local campplus=$HF/funasr/campplus/resolve/e4b6ede7ce16997aff4ae69fbca1f0175e2afede
  local bigvgan=$HF/nvidia/bigvgan_v2_22khz_80band_256x/resolve/633ff708ed5b74903e86ff1298cf4a98e921c513
  checkout https://github.com/index-tts/index-tts.git "$root" d9e41aac89fd00b3d71497fddb287b7f24613712
  (cd "$root" && uv sync --locked --no-dev --python 3.11)
  (cd "$root" && .venv/bin/python -c 'from indextts.infer_v2_5 import IndexTTS2')
  stage_all "IndexTTS2.5 下载" \
    "$model/config.yaml|$repo/config.yaml|2860|" \
    "$model/gpt.pth|$repo/gpt.pth|3259599833|" \
    "$model/s2mel.pth|$repo/s2mel.pth|414908601|" \
    "$model/codec.pth|$repo/codec.pth|607290935|" \
    "$model/wav2vec2bert_stats.pt|$repo/wav2vec2bert_stats.pt|9343|" \
    "$model/multilingual_zh_ja_yue_char_del.tiktoken|$repo/multilingual_zh_ja_yue_char_del.tiktoken|907395|" \
    "$model/hf_cache/w2v-bert-2.0/config.json|$w2v/config.json|1874|" \
    "$model/hf_cache/w2v-bert-2.0/preprocessor_config.json|$w2v/preprocessor_config.json|275|" \
    "$model/hf_cache/w2v-bert-2.0/model.safetensors|$w2v/model.safetensors|2322063736|" \
    "$model/hf_cache/campplus_cn_common.bin|$campplus/campplus_cn_common.bin|28036335|" \
    "$model/hf_cache/bigvgan/config.json|$bigvgan/config.json|1405|" \
    "$model/hf_cache/bigvgan/bigvgan_generator.pt|$bigvgan/bigvgan_generator.pt|449228171|"
}

yue2() {
  local venv=/content/yue2-venv
  local yue=$HF/m-a-p/YuE2-3B/resolve/14fc6c6f146441b1dd6363fcb2e01e82a6914cb7
  local vae=$HF/m-a-p/YuE2-Vae/resolve/9a94e1d0ea9f8087e98f77fa88df4a4068104d2a
  local wheel=yue2_infer-0.1.5-py3-none-any.whl
  stage_all "YuE2 下载" \
    "$CACHE/$wheel|$yue/$wheel|66117|" \
    "$CACHE/YuE2-3B/config.json|$yue/config.json|959|" \
    "$CACHE/YuE2-3B/weights_manifest.json|$yue/weights_manifest.json|179|" \
    "$CACHE/YuE2-3B/model.safetensors|$yue/model.safetensors|7261441640|" \
    "$CACHE/YuE2-3B/qwen.tiktoken|$yue/qwen.tiktoken|2561218|" \
    "$CACHE/YuE2-3B/generation_config.json|$yue/generation_config.json|204|" \
    "$CACHE/YuE2-3B/yue2_generation_config.json|$yue/yue2_generation_config.json|466|" \
    "$CACHE/YuE2-Vae/config.json|$vae/config.json|1378|" \
    "$CACHE/YuE2-Vae/weights_manifest.json|$vae/weights_manifest.json|178|" \
    "$CACHE/YuE2-Vae/model.safetensors|$vae/model.safetensors|530512720|"
  echo "8801e2c0d969db02df78d2994150b4ccd86077d87c24fdb8509b1f6f31462641  $CACHE/$wheel" | sha256sum -c -
  cuda_env "$venv" 3.12 2.10.0
  uv pip install -q --python "$venv/bin/python" "$CACHE/$wheel"
  "$venv/bin/python" -c 'from yue2 import YuE2Pipeline'
}

stable_audio_3() {
  local root=/content/stable-audio-3 venv=/content/stable-audio-3-venv
  local token=/root/.slatehand-colab-hf-token
  if [ ! -s "$token" ]; then
    echo "Stable Audio 3 需要具有 Medium 权重下载权限的 Hugging Face Token。" >&2
    return 1
  fi
  checkout https://github.com/Stability-AI/stable-audio-3.git "$root" 790793b89ddceea612be9ce42ff6830d18f6fa57
  cuda_env "$venv" 3.12 2.7.1 torchaudio==2.7.1
  uv pip install -q --python "$venv/bin/python" "$root"
  HF_HOME=/content/stable-audio-3-hf HF_TOKEN_PATH="$token" "$venv/bin/python" - <<'PY'
from pathlib import Path

from huggingface_hub import snapshot_download

repo = "stabilityai/stable-audio-3-medium"
revision = "d4d3579395a8ac0df4ab13b5b1d7138ce7290f81"
snapshot = Path(snapshot_download(
    repo, revision=revision,
    allow_patterns=["model_config.json", "model.safetensors", "t5gemma-b-b-ul2/*"],
))
# 上游 from_pretrained("medium") 离线读取 main；本节点的独立缓存绑定到固定快照。
refs = snapshot.parent.parent / "refs"
refs.mkdir(exist_ok=True)
pending = refs / "main.part"
pending.write_text(revision, encoding="ascii")
pending.replace(refs / "main")
PY
  HF_HUB_OFFLINE=1 "$venv/bin/python" -c 'from stable_audio_3 import StableAudioModel'
}

demucs() {
  local venv=/content/demucs-venv
  cuda_env "$venv" 3.12 2.8.0 torchaudio==2.8.0
  uv pip install -q --python "$venv/bin/python" demucs==4.0.1
  TORCH_HOME=/content/demucs-torch "$venv/bin/python" -c 'from demucs.pretrained import get_model; get_model("htdemucs")'
}

whisper() {
  local root=/content/whisper.cpp
  local repo=$HF/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1
  checkout https://github.com/ggml-org/whisper.cpp.git "$root" 96ec4d9823e9d0211944172da35f9f29134af990
  cmake -S "$root" -B "$root/build" -DCMAKE_BUILD_TYPE=Release -DWHISPER_BUILD_TESTS=OFF
  cmake --build "$root/build" --target whisper-cli -j 4
  stage_all "Whisper 下载" \
    "$CACHE/ggml-large-v3-turbo-q5_0.bin|$repo/ggml-large-v3-turbo-q5_0.bin|574041195|"
}
