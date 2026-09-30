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

# Mesa 26.3 requires Meson >= 1.4. Bookworm ships 1.0.1 in its main
# repository, while bookworm-backports provides a suitable Debian package.
if [ "$DEBIAN_RELEASE" = bookworm ]; then
  printf 'deb http://deb.debian.org/debian bookworm-backports main\n' \
    > /etc/apt/sources.list.d/bookworm-backports.list
  apt-get update
  apt-get install --yes --no-install-recommends -t bookworm-backports meson
fi

apt-get install --yes --no-install-recommends \
  ca-certificates \
  debhelper \
  devscripts \
  dpkg-dev \
  equivs \
  fakeroot \
  git \
  meson \
  quilt

meson --version

mkdir -p /build
git clone --filter=blob:none --no-checkout \
  https://gitlab.freedesktop.org/mesa/mesa.git /build/mesa
git -C /build/mesa checkout --detach "$MESA_REF"
git -C /build/mesa config user.name "Mesa grate build"
git -C /build/mesa config user.email mesa-grate@users.noreply.github.com
git -C /build/mesa am --3way --keep-non-patch < /src/mesa-grate.patch

git clone --depth=1 --branch "$DEBIAN_PACKAGING_BRANCH" \
  "$DEBIAN_PACKAGING_REPOSITORY" /build/debian-mesa
cp -a /build/debian-mesa/debian /build/mesa/debian
cd /build/mesa

rm -f debian/patches/*
: > debian/patches/series

# The Trixie packaging rewrites Rust wraps from Mesa 25.x. Mesa 26.3 no
# longer has those wrap files, and Rusticl is not needed for grate.
sed -i 's/^override_dh_auto_configure: rewrite_wrap_files$/override_dh_auto_configure:/' debian/rules

# Both Debian packaging branches enable frontends removed from Mesa 26.3.
# Keep LLVM for llvmpipe and build only the driver/frontend features needed
# for the Surface RT package.
sed -i '/^empty:=/i confflags_GALLIUM = -Dllvm=enabled -Ddraw-use-llvm=true -Dgallium-rusticl=false -Dgallium-va=disabled' debian/rules
sed -i '/^empty:=/i confflags_OSMESA =' debian/rules
sed -i '/^empty:=/i confflags_DRI3 =' debian/rules

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
