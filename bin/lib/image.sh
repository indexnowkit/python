# shellcheck shell=bash
# Sourced by bin/python and bin/uv. image_for <python version> prints the development image tag, building it once:
# indexnowkit-python:<version>-<hash of docker/python/Dockerfile>, so editing the Dockerfile rebuilds and nothing else does.
# run_in_image <version> <dir> <cmd...> runs a command in that image with the workspace mounted at /app; the uv cache
# and the environment of each Python version live under var/ (git-ignored), so switching PYTHON_VERSION never clobbers.
image_for() {
    local ver="$1" dir="$ROOT/docker/python" hash tag
    hash="$(shasum -a 256 "$dir/Dockerfile" | cut -c1-12)"
    tag="indexnowkit-python:${ver}-${hash}"
    if ! docker image inspect "$tag" >/dev/null 2>&1; then
        echo "building ${tag} from docker/python/Dockerfile" >&2
        docker build --quiet --build-arg "PYTHON_VERSION=${ver}" --tag "$tag" "$dir" >/dev/null
    fi
    printf '%s' "$tag"
}

run_in_image() {
    local ver="$1" dir="$2" image
    shift 2
    image="$(image_for "$ver")"
    mkdir -p "$ROOT/var/uv-cache" "$ROOT/var/venv"
    local tty=()
    [ -t 0 ] && [ -t 1 ] && tty=(-it)
    exec docker run --rm ${tty[@]+"${tty[@]}"} \
        -v "$ROOT:/app" \
        -e "UV_PROJECT_ENVIRONMENT=/app/var/venv/${ver}" \
        -w "/app/$dir" "$image" "$@"
}
