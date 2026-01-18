#!/bin/sh
source .venv/bin/activate
# Use PORT if it's set, otherwise default to 8081
python -u -m flask --app main run --debug -p ${PORT:-8081}
