#!/usr/bin/env bash
# Build a flattened, stripped xtalk base image for the round-one stack.
#
# `xtalk:v0.17` is a 431-layer chain whose later layers supersede files from
# earlier ones (notably a 2.59 GB `vllm==0.10.2` layer replaced later by
# `vllm==0.16.0`); those dead bytes still ship.  It also carries stacks the
# round-one stack does not use (paraformer/onnxruntime, IndexTTS/pynini,
# gradio/wandb/kubernetes/verl, node).  This script:
#   1. flatten xtalk:v0.17 with `export | import` (431 -> 1 layer, ~32 -> 25 GB)
#   2. strip the unused components in a build layer, then flatten again
#      (~25 -> 22 GB), keeping vLLM hard deps (ray/numba/opencv/pyarrow/triton).
#
# Requires a Docker daemon where build steps run as root (the strip needs to
# delete root-owned files); the cluster lets `docker build` do so.
#
# Usage:
#   bash scripts/remote/build_xtalk_lean_base.sh
#   PUSH=1 bash scripts/remote/build_xtalk_lean_base.sh
#
# Overrides: XTALK_BASE_IMAGE, XTALK_LEAN_IMAGE, PUSH
set -euo pipefail

SRC="${XTALK_BASE_IMAGE:-docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk:v0.17}"
DST="${XTALK_LEAN_IMAGE:-docker.v2.aispeech.com/sjtu/sjtu_yukai-xuanzhang-xtalk-lean:v0.1}"
PUSH="${PUSH:-0}"
WORK="$(mktemp -d)"
FLAT_RAW="xzflat-raw:tmp"
STRIP_TMP="xzstrip:tmp"

IMPORT_CONFIG=(
  -c "ENV PATH=/opt/node/bin:/usr/local/nvidia/bin:/usr/local/cuda/bin:/opt/conda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
  -c "WORKDIR /opt/xtalk"
  -c "ENV LANG=C.UTF-8" -c "ENV LC_ALL=C.UTF-8"
  -c "ENV DEBIAN_FRONTEND=noninteractive" -c "ENV PYTHONUNBUFFERED=1"
  -c "ENV PYTHONNOUSERSITE=True"
  -c "ENV LD_LIBRARY_PATH=/usr/local/nvidia/lib:/usr/local/nvidia/lib64"
  -c "ENV NVIDIA_VISIBLE_DEVICES=all" -c "ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility"
  -c "ENV CUDA_VERSION=12.8.1"
)

flatten() {  # flatten <image> <dest-tag>
  local image="$1" dest="$2" cid
  docker rm -f "$(docker ps -aqf "name=icflatten")" >/dev/null 2>&1 || true
  docker create --name icflatten "$image" true >/dev/null
  cid="$(docker ps -aqf "name=icflatten" | head -1)"
  docker export "$cid" | docker import "${IMPORT_CONFIG[@]}" - "$dest"
}

cat > "$WORK/strip_base.sh" <<'STRIP'
#!/usr/bin/env bash
# Remove components unused by the round-one stack; keep vLLM hard deps.
set -eux
sp=/opt/conda/lib/python3.11/site-packages
rm -rf \
  "$sp"/onnxruntime "$sp"/onnxruntime-*.dist-info "$sp"/onnxruntime_gpu-*.dist-info \
  "$sp"/funasr "$sp"/funasr-*.dist-info "$sp"/modelscope "$sp"/modelscope-*.dist-info \
  "$sp"/sherpa_onnx "$sp"/sherpa_onnx.libs "$sp"/sherpa_onnx-*.dist-info "$sp"/sherpa_onnx_core-*.dist-info \
  "$sp"/pynini "$sp"/pynini.libs "$sp"/pynini-*.dist-info "$sp"/_pynini*.so \
  "$sp"/pyopenjtalk "$sp"/pyopenjtalk-*.dist-info "$sp"/descript_audiotools-*.dist-info \
  "$sp"/gradio "$sp"/gradio-*.dist-info "$sp"/gradio_client "$sp"/gradio_client-*.dist-info \
  "$sp"/wandb "$sp"/wandb-*.dist-info "$sp"/kubernetes "$sp"/kubernetes-*.dist-info \
  "$sp"/tensorboard "$sp"/tensorboard-*.dist-info "$sp"/tensorboardX "$sp"/tensorboardx-*.dist-info \
  "$sp"/tensorboard_data_server "$sp"/tensorboard_data_server-*.dist-info \
  "$sp"/verl "$sp"/verl-*.dist-info "$sp"/cosyvoice_local-*.dist-info \
  "$sp"/pytriton "$sp"/nvidia_pytriton-*.dist-info "$sp"/nvidia_pytriton.libs \
  "$sp"/xformers "$sp"/xformers-*.dist-info \
  "$sp"/cupy "$sp"/cupy_backends "$sp"/cupyx "$sp"/cupy_cuda12x-*.dist-info \
  /opt/node-v24.14.0-linux-x64 /opt/xtalk
echo STRIP_DONE
STRIP

echo "[lean] flattening $SRC -> $FLAT_RAW"
flatten "$SRC" "$FLAT_RAW"

echo "[lean] stripping in a build layer"
cat > "$WORK/Dockerfile" <<DOCKER
FROM $FLAT_RAW
COPY strip_base.sh /tmp/strip_base.sh
RUN bash /tmp/strip_base.sh
DOCKER
DOCKER_BUILDKIT=1 docker build -f "$WORK/Dockerfile" -t "$STRIP_TMP" "$WORK"

echo "[lean] re-flattening -> $DST"
flatten "$STRIP_TMP" "$DST"
docker image inspect "$DST" --format '{{.Size}} bytes, {{len .RootFS.Layers}} layer(s)'

if [ "$PUSH" = "1" ]; then
  docker push "$DST"
  echo "[lean] pushed $DST"
fi

docker rmi "$FLAT_RAW" "$STRIP_TMP" >/dev/null 2>&1 || true
rm -rf "$WORK"
echo "[lean] done"
