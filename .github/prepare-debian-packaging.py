#!/usr/bin/env python3
"""Adapt the Debian Mesa packaging to the small Mesa grate build."""

import argparse
import re
from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    contents = path.read_text()
    if contents.count(old) != 1:
        raise RuntimeError(f"expected exactly one occurrence of {old!r} in {path}")
    path.write_text(contents.replace(old, new))


def drop_packages(path: Path, names: set[str]) -> None:
    paragraphs = path.read_text().strip().split("\n\n")
    found = set()
    kept = []
    for paragraph in paragraphs:
        match = re.match(r"Package: (\S+)$", paragraph, re.MULTILINE)
        if match and match.group(1) in names:
            found.add(match.group(1))
        else:
            kept.append(paragraph)
    if found != names:
        raise RuntimeError(f"missing package stanzas in {path}: {names - found}")
    path.write_text("\n\n".join(kept) + "\n")


def append_install(path: Path, entry: str) -> None:
    contents = path.read_text()
    if entry not in contents.splitlines():
        path.write_text(contents.rstrip("\n") + "\n" + entry + "\n")


def require_gallium(path: Path) -> None:
    names = {"libgbm1", "libegl-mesa0", "libglx-mesa0", "libgl1-mesa-dri"}
    paragraphs = path.read_text().strip().split("\n\n")
    found = set()
    for index, paragraph in enumerate(paragraphs):
        match = re.match(r"Package: (\S+)$", paragraph, re.MULTILINE)
        if match and match.group(1) in names:
            found.add(match.group(1))
            if paragraph.count("Depends:\n") != 1:
                raise RuntimeError(f"unexpected Depends field in {path}: {match.group(1)}")
            paragraphs[index] = paragraph.replace(
                "Depends:\n", "Depends:\n mesa-libgallium (= ${binary:Version}),\n", 1
            )
    if found != names:
        raise RuntimeError(f"missing core package stanzas in {path}: {names - found}")
    path.write_text("\n\n".join(paragraphs) + "\n")


def update_trixie_symbols() -> None:
    # Mesa 26.3's GLVND vendor library no longer exports the OpenGL entrypoints
    # listed by Trixie's older GLX symbols file. Keep its four vendor exports.
    glx = Path("debian/libglx-mesa0.symbols")
    lines = glx.read_text().splitlines()
    old_gl_entries = [line for line in lines if line.startswith(" gl")]
    if len(old_gl_entries) < 1000 or len(lines) - len(old_gl_entries) != 5:
        raise RuntimeError("unexpected Trixie GLX symbols layout")
    glx.write_text("\n".join(line for line in lines if not line.startswith(" gl")) + "\n")

    # These three EGL interop entrypoints are present in the Mesa 26.3 build.
    egl = Path("debian/libegl-mesa0.symbols")
    old = "libEGL_mesa.so.0 libegl-mesa0 #MINVER#\n __egl_Main@Base 17.0.0~\n"
    new = (
        "libEGL_mesa.so.0 libegl-mesa0 #MINVER#\n"
        " MesaGLInteropEGLExportObject@Base 26.3.0+grate1\n"
        " MesaGLInteropEGLFlushObjects@Base 26.3.0+grate1\n"
        " MesaGLInteropEGLQueryDeviceInfo@Base 26.3.0+grate1\n"
        " __egl_Main@Base 17.0.0~\n"
    )
    if egl.read_text() != old:
        raise RuntimeError("unexpected Trixie EGL symbols layout")
    egl.write_text(new)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("release", choices=("bookworm", "trixie"))
    release = parser.parse_args().release

    # Grate takes the tegra DRM slot, but the upstream DRI target only makes
    # tegra_dri.so when Mesa's newer Tegra K1+ driver is selected.
    replace_once(
        Path("src/gallium/targets/dril/meson.build"),
        "[with_gallium_tegra, ['tegra']]",
        "[with_gallium_tegra or with_gallium_grate, ['tegra']]",
    )

    rules = Path("debian/rules")
    contents = rules.read_text()
    start = "  ifneq ($(DEB_HOST_ARCH_OS), hurd)\n\t# Copy the hardlinked vdpau drivers correctly."
    end = "\n\tdh_install -a"
    if contents.count(start) != 1 or contents.count(end) != 1:
        raise RuntimeError("unexpected Debian install rules layout")
    before, remainder = contents.split(start, 1)
    _, after = remainder.split(end, 1)
    contents = before + "\tdh_install -a" + after

    if release == "bookworm":
        # Bookworm's rules predate both the pinned Mesa source and its build
        # options. There is no standalone libglapi.so in this Mesa build.
        contents = contents.replace(
            "\trm debian/tmp/usr/lib/*/libglapi.so\n",
            "\trm -f debian/tmp/usr/lib/*/libglapi.so\n",
        )
        contents = "\n".join(
            line for line in contents.split("\n")
            if "-Ddri-search-path=" not in line and "-Dgallium-omx=" not in line
        )
    rules.write_text(contents)

    unavailable = {
        "libd3dadapter9-mesa",
        "libd3dadapter9-mesa-dev",
        "libosmesa6",
        "libosmesa6-dev",
        "mesa-va-drivers",
        "mesa-vdpau-drivers",
        "mesa-vulkan-drivers",
        "mesa-opencl-icd",
    }
    if release == "trixie":
        unavailable.add("mesa-drm-shim")
    else:
        unavailable.add("libglapi-mesa")

    for name in ("control.in", "control"):
        drop_packages(Path("debian") / name, unavailable)

    # Keep the new shared Gallium library in a version-matched package. It is
    # already present in Trixie's package list, but Bookworm predates it.
    if release == "bookworm":
        gallium = (
            "\nPackage: mesa-libgallium\n"
            "Section: libs\n"
            "Architecture: linux-any\n"
            "Depends:\n"
            " ${shlibs:Depends},\n"
            " ${misc:Depends},\n"
            "Pre-Depends: ${misc:Pre-Depends}\n"
            "Multi-Arch: same\n"
            "Description: shared infrastructure for Mesa drivers\n"
            " This package contains Mesa's private shared Gallium library.\n"
        )
        for name in ("control.in", "control"):
            path = Path("debian") / name
            path.write_text(path.read_text().rstrip("\n") + "\n" + gallium)
            require_gallium(path)
        Path("debian/mesa-libgallium.install").write_text(
            "usr/lib/*/libgallium-*.so\n"
        )

    append_install(Path("debian/libgbm-dev.install"), "usr/include/gbm_backend_abi.h")
    if release == "bookworm":
        append_install(Path("debian/libgbm1.install"), "usr/lib/*/gbm/dri_gbm.so")
    else:
        update_trixie_symbols()


if __name__ == "__main__":
    main()
