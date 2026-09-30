#!/usr/bin/env bash
set -euxo pipefail

: "${DEBIAN_RELEASE:?DEBIAN_RELEASE is required}"
: "${DEBIAN_PACKAGING_BRANCH:?DEBIAN_PACKAGING_BRANCH is required}"
: "${MESA_REF:?MESA_REF is required}"
: "${DEBIAN_PACKAGING_REPOSITORY:?DEBIAN_PACKAGING_REPOSITORY is required}"

export DEBIAN_FRONTEND=noninteractive
export DEBEMAIL=mesa-grate@users.noreply.github.com
export DEBFULLNAME="Mesa grate build"

apt-get update
apt-get install --yes --no-install-recommends \
  ca-certificates \
  debhelper \
  devscripts \
  dpkg-dev \
  equivs \
  fakeroot \
  git \
  quilt

mkdir -p /build
git clone --filter=blob:none --no-checkout \
  https://gitlab.freedesktop.org/mesa/mesa.git /build/mesa
git -C /build/mesa checkout --detach "$MESA_REF"
git -C /build/mesa am --3way --keep-non-patch < /src/mesa-grate.patch

git clone --depth=1 --branch "$DEBIAN_PACKAGING_BRANCH" \
  "$DEBIAN_PACKAGING_REPOSITORY" /build/debian-mesa
cp -a /build/debian-mesa/debian /build/mesa/debian
cd /build/mesa

rm -f debian/patches/*
: > debian/patches/series

sed -i '/^empty:=/i VULKAN_LAYERS =' debian/rules
sed -i '/^empty:=/i VULKAN_DRIVERS =' debian/rules
sed -i '/^empty:=/i GALLIUM_DRIVERS = grate llvmpipe softpipe' debian/rules

dch --distribution "$DEBIAN_RELEASE" \
  --newversion "26.3.0+grate1-1~${DEBIAN_RELEASE}1" \
  "Build Mesa with the Surface RT grate driver."

mk-build-deps --install --remove \
  --tool 'apt-get --yes --no-install-recommends' debian/control
dpkg-buildpackage -us -uc -b -j2

mkdir -p "/src/artifacts/${DEBIAN_RELEASE}"
cp -v /build/*.deb "/src/artifacts/${DEBIAN_RELEASE}/"
dpkg-deb --info /build/libgl1-mesa-dri_*.deb | sed -n '1,30p'