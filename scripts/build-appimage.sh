#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ ! -x release/ps5-downloader-gui-linux-x86_64 ]]; then
  scripts/build-desktop-linux.sh
fi

APPDIR="build/appimage/PS5_Downloader.AppDir"
rm -rf "${APPDIR}"
mkdir -p "${APPDIR}/usr/bin" "${APPDIR}/usr/share/applications" "${APPDIR}/usr/share/icons/hicolor/256x256/apps" release
cp release/ps5-downloader-gui-linux-x86_64 "${APPDIR}/usr/bin/ps5-downloader-gui"
cat > "${APPDIR}/AppRun" <<'EOF'
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/ps5-downloader-gui" "$@"
EOF
chmod +x "${APPDIR}/AppRun"
cat > "${APPDIR}/ps5-downloader.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=PS5 Downloader
Exec=ps5-downloader-gui
Icon=ps5-downloader
Categories=Network;Utility;
Terminal=false
EOF
cp "${APPDIR}/ps5-downloader.desktop" "${APPDIR}/usr/share/applications/ps5-downloader.desktop"
cat > "${APPDIR}/ps5-downloader.svg" <<'EOF'
<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
  <rect width="256" height="256" rx="32" fill="#111820"/>
  <path d="M128 34v118" stroke="#54c58a" stroke-width="24" stroke-linecap="round"/>
  <path d="M78 114l50 50 50-50" fill="none" stroke="#54c58a" stroke-width="24" stroke-linecap="round" stroke-linejoin="round"/>
  <rect x="55" y="190" width="146" height="24" rx="12" fill="#d8f3e4"/>
</svg>
EOF
cp "${APPDIR}/ps5-downloader.svg" "${APPDIR}/usr/share/icons/hicolor/256x256/apps/ps5-downloader.svg"

APPIMAGETOOL="${APPIMAGETOOL:-/tmp/appimagetool-x86_64.AppImage}"
if [[ ! -x "${APPIMAGETOOL}" ]]; then
  curl -L --fail -o "${APPIMAGETOOL}" "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
  chmod +x "${APPIMAGETOOL}"
fi

ARCH=x86_64 "${APPIMAGETOOL}" "${APPDIR}" "release/PS5_Downloader-0.1.0-x86_64.AppImage"
sha256sum release/PS5_Downloader-0.1.0-x86_64.AppImage > release/PS5_Downloader-0.1.0-x86_64.AppImage.sha256
