#!/bin/bash
# usage: grade.sh AGENT.patch  -> runs F2P+P2P for flask-4992 on a clean checkout
set -e
R=/home/user/work/pallets__flask-4992
cd $R && git reset -q --hard && git clean -qfd
git apply "$1" && git apply /home/user/pilot/test.patch
/home/user/venv-flask/bin/python -m pytest -q tests/test_config.py 2>&1 | tail -3
git reset -q --hard && git clean -qfd
