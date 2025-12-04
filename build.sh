#!/bin/bash
set -e

rm -rf build
git clone "https://aur.archlinux.org/$1.git" build
cd build || exit 1
makepkg -sf --noconfirm
rm -rf ~/pkg
mkdir ~/pkg
cp -v *.{pkg.tar.zst} ~/pkg
