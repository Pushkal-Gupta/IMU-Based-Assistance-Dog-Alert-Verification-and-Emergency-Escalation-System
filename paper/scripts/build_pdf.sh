#!/usr/bin/env bash
# Build paper/build/main.pdf with Tectonic (XeTeX).
#
# MDPI's class includes Illustrator EPS logos, which XeTeX cannot embed.  The
# submitted sources keep MDPI's files untouched; for the local build we copy
# the sources into build/src and convert those two logos to PDF with
# Ghostscript, pointing the build copy of the class at the PDFs.
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf build/src && mkdir -p build/src
cp -R main.tex references.bib sections figures generated Definitions build/src/
for eps in build/src/Definitions/*.eps; do
  gs -q -dSAFER -dBATCH -dNOPAUSE -dEPSCrop -sDEVICE=pdfwrite -o "${eps%.eps}.pdf" "$eps"
done
sed -i.bak 's/\(logo-[a-z-]*\)\.eps/\1.pdf/g' build/src/Definitions/mdpi.cls
cd build/src
tectonic -X compile main.tex --keep-logs
cp main.pdf ../main.pdf
cp main.log ../main.log
echo "wrote paper/build/main.pdf"
