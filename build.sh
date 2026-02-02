#!/bin/bash
set -e

package=$1
shift

sudo pacman -Syu

for dep in "$@"; do
    sudo pacman -U ~/deps/$dep/*.pkg.tar.zst --noconfirm
done

rm -rf build
git clone "https://aur.archlinux.org/$package.git" build
cd build || exit 1
makepkg -sf --noconfirm
mkdir ~/pkg || true
cp -v *.pkg.tar.zst ~/pkg
cp -v *.tar.gz ~/pkg || true
