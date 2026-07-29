#!/bin/bash
set -e
cd /home/site/wwwroot
export PYTHONPATH=/home/site/wwwroot:/home/site/wwwroot/.python_packages/lib/site-packages
python3 scripts/probe_sharepoint_list_capability.py
