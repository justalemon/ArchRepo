#!/bin/bash
set -e

package=$1
shift
commit=$1
shift

sudo pacman -Syu --noconfirm

for dep in "$@"; do
    sudo pacman -U ~/deps/$dep/*.pkg.tar.zst --noconfirm
done

rm -rf build
git clone "https://aur.archlinux.org/$package.git" build
cd build || exit 1
git checkout "$commit"
makepkg -sf --noconfirm
mkdir ~/pkg || true
rm -rf ~/pkg/*
cp -v *.pkg.tar.* ~/pkg
cp -v *.tar.gz ~/pkg || true
