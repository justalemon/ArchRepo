#!/bin/bash
set -e

cd /home/builder/repo
repo-add $1.db.tar.zst *.pkg.tar.*
