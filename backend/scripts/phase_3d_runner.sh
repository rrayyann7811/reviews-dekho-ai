#!/usr/bin/env bash
set -Eeuo pipefail

base=809c0230490260f560c802cf8cecc5bd992dd284
image=docker.io/library/python@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f
expected=$'.github/workflows/phase-3d-bounded-onnx.yml\nbackend/scripts/phase_3d_runner.sh\nbackend/scripts/phase_3d_workload.py'
test "$(git rev-parse HEAD^)" = "$base"
test "$(git diff --name-only "$base" HEAD)" = "$expected"
test "$(uname -m)" = x86_64
test "$(docker info --format '{{.OSType}}/{{.Architecture}}/{{.CgroupVersion}}')" = linux/x86_64/2
cpu="$(awk '/^Cpus_allowed_list:/ { split($2, ids, /[-,]/); print ids[1] }' /proc/self/status)"
[[ "$cpu" =~ ^[0-9]+$ ]]

scratch="$(mktemp -d "$RUNNER_TEMP/phase-3d.XXXXXXXX")"
container_id=
cleanup() {
  if [[ -n "$container_id" ]]; then
    docker rm -f "$container_id" >/dev/null || true
  fi
  rm -rf -- "$scratch"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

bundle="$scratch/function"
state="$scratch/state"
mkdir "$bundle" "$state" "$scratch/wheels"
cp -a backend/app backend/alembic backend/alembic.ini "$bundle/"
sed '/^pytest==/d; /^uvicorn\[standard\]==/d' backend/requirements.txt > "$bundle/requirements.txt"
printf '3.14\n' > "$bundle/.python-version"
printf '{"functions":{"app/main.py":{"maxDuration":45}}}\n' > "$bundle/vercel.json"

python -m pip download --disable-pip-version-check --no-cache-dir --only-binary=:all: \
  --dest "$scratch/wheels" -r "$bundle/requirements.txt"
sha256sum "$scratch"/wheels/*.whl | sed "s|$scratch/wheels/||"
python -m pip install --disable-pip-version-check --no-index --find-links "$scratch/wheels" \
  --only-binary=:all: --no-compile --target "$bundle" -r "$bundle/requirements.txt"
python -m pip list --path "$bundle" --format=freeze
export BUNDLE="$bundle" MODEL_DIR="$bundle/models/twitter-roberta-sentiment"
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$bundle"
timeout --kill-after=5s 120s python -S backend/scripts/download_model.py
python -S - <<'PY' | tee -a "$GITHUB_STEP_SUMMARY"
import hashlib
import os
import runpy
from pathlib import Path

bundle = Path(os.environ["BUNDLE"])
for name, expected in runpy.run_path("backend/scripts/download_model.py")["FILES"].items():
    path = Path(os.environ["MODEL_DIR"]) / Path(name).name
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    assert actual == expected, path.name
    print(f"{path.name} sha256={actual}")
size = sum(path.stat().st_size for path in bundle.rglob("*") if path.is_file())
print(f"Function-only tree: {size:,} bytes ({size / 1e6:.2f} MB)")
print(f"Standard 500 MB: {'FIT' if size <= 500_000_000 else 'OVER'}")
print(f"Large Functions 5 GB size only: {'FIT' if size <= 5_000_000_000 else 'OVER'}")
PY
rm -rf -- "$scratch/wheels"
cp backend/scripts/phase_3d_workload.py "$scratch/workload.py"

docker pull --platform linux/amd64 "$image"
start="$(date -u +%FT%T.%NZ)"
container_id="$(docker create --platform linux/amd64 --pull=never \
  --name "phase-3d-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}" \
  --cpus=1 --cpuset-cpus="$cpu" --memory=2g --memory-swap=2g --pids-limit=128 \
  --network=none --security-opt=no-new-privileges --cap-drop=ALL \
  --user "$(id -u):$(id -g)" \
  --mount "type=bind,src=$bundle,dst=/function,readonly" \
  --mount "type=bind,src=$state,dst=/state" \
  --mount "type=bind,src=$scratch/workload.py,dst=/workload.py,readonly" \
  -e PYTHONPATH=/function -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONFAULTHANDLER=1 \
  -e MODEL_DIR=/function/models/twitter-roberta-sentiment -e TMPDIR=/state \
  "$image" python -S -u /workload.py suite)"
set +e
timeout --kill-after=10s 600s docker start -a "$container_id"
attach_status=$?
set -e
docker inspect --format '{{json .State}}' "$container_id"
docker inspect --format 'Docker limits: memory={{.HostConfig.Memory}} swap total={{.HostConfig.MemorySwap}} nanoCPUs={{.HostConfig.NanoCpus}} cpuset={{.HostConfig.CpusetCpus}}' "$container_id"
end="$(date -u +%FT%T.%NZ)"
oom="$(docker events --since "$start" --until "$end" --filter "container=$container_id" \
  --filter "event=oom" --format '{{json .}}')"
if [[ -n "$oom" ]]; then printf 'Docker OOM event: %s\n' "$oom"; fi
if [[ -f "$state/results.jsonl" ]]; then
  {
    printf '\n### Workload telemetry\n\n```jsonl\n'
    cat "$state/results.jsonl"
    printf '```\n'
  } >> "$GITHUB_STEP_SUMMARY"
fi
test "$attach_status" -eq 0
test "$(docker inspect --format '{{.State.ExitCode}}/{{.State.OOMKilled}}' "$container_id")" = 0/false
test -z "$oom"
test -f "$state/suite-passed"
