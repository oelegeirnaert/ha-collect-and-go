# Collect & Go add-on — developer tasks
# Docs: https://just.systems  ·  run `just` to list all recipes

set shell := ["bash", "-cu"]

# Paths
venv       := ".venv"
py         := venv / "bin/python"
app_dir    := "collect_and_go/app"
data_dir   := env_var_or_default("DATA_DIR", "/tmp/cg-data")
addon_dir  := "collect_and_go"
image      := "ha-collect-and-go"
build_base := "ghcr.io/home-assistant/amd64-base-python:3.13-alpine3.21"

default:
    @just --list

# ---------- local development ----------

# One-time setup: create the venv and install dependencies
setup:
    #!/usr/bin/env bash
    set -e
    if [ ! -d {{venv}} ]; then python3 -m venv {{venv}}; fi
    {{py}} -m pip install --quiet --upgrade pip
    {{py}} -m pip install --quiet -r {{addon_dir}}/requirements.txt
    echo "venv ready at {{venv}}"

# Run the add-on locally (no Docker) at http://127.0.0.1:8099
run: setup
    cd {{app_dir}} && DATA_DIR={{data_dir}} {{justfile_directory()}}/{{py}} main.py

# Same, but auto-reloads on code changes
dev: setup
    cd {{app_dir}} && DATA_DIR={{data_dir}} {{justfile_directory()}}/{{py}} -m uvicorn main:app --host 127.0.0.1 --port 8099 --reload

# ---------- checks ----------

# Syntax-check all Python files and validate YAML manifests
check:
    {{py}} -c "import ast,glob; [ast.parse(open(f).read()) for f in glob.glob('{{app_dir}}/**/*.py', recursive=True)]; print('python syntax OK')"
    {{py}} -c "import yaml; [yaml.safe_load(open(f)) for f in ['repository.yaml','{{addon_dir}}/config.yaml','{{addon_dir}}/build.yaml','{{addon_dir}}/translations/en.yaml','{{addon_dir}}/translations/nl.yaml']]; print('yaml OK')"

# ---------- Docker (closest to Home Assistant) ----------

# Build the add-on image for this machine's architecture
docker-build:
    docker build --build-arg BUILD_FROM={{build_base}} -t {{image}}:local {{addon_dir}}

# Run the built image at http://127.0.0.1:8099 (persists data in ./.dev-data)
docker-run: docker-build
    mkdir -p .dev-data
    docker run --rm -p 8099:8099 -v "$PWD/.dev-data:/data" --name cg-local {{image}}:local

docker-stop:
    docker stop cg-local || true

# ---------- releasing ----------

# Release a new version: `just release patch "Fixed the add crash"`
release TYPE NOTE:
    ./release.sh {{TYPE}} "{{NOTE}}"

# ---------- cleanup ----------

# Remove the venv, dev data and local docker image
clean:
    rm -rf {{venv}} .dev-data
    docker rmi {{image}}:local 2>/dev/null || true
