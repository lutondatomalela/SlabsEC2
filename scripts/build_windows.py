"""Compilar o executável autónomo em Windows x64."""
import json
import platform
from pathlib import Path
import runpy
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.platform != "win32" or struct.calcsize("P") != 8:
        raise SystemExit("A compilação requer Windows e Python de 64 bits.")
    version = runpy.run_path(str(ROOT / "slabsec2/version.py"))["VERSION"]
    numbers = tuple(int(x) for x in version.split("-")[0].split(".")) + (1,)
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    metadata = build / "windows-version.txt"
    strings = {
        "CompanyName": "Lutonda Adolph Tomalela",
        "FileDescription": "SlabsEC2 — Lajes maciças de betão armado",
        "FileVersion": ".".join(map(str, numbers)),
        "InternalName": "SlabsEC2",
        "OriginalFilename": "SlabsEC2.exe",
        "ProductName": "SlabsEC2",
        "ProductVersion": version,
        "LegalCopyright": "Copyright (c) 2026 Lutonda Adolph Tomalela. Licença MIT.",
    }
    entries = ",".join(f"StringStruct({key!r}, {value!r})" for key, value in strings.items())
    metadata.write_text(
        f"VSVersionInfo(ffi=FixedFileInfo(filevers={numbers!r}, prodvers={numbers!r}, mask=0x3f, flags=2, OS=0x40004, fileType=1, subtype=0, date=(0,0)), "
        f"kids=[StringFileInfo([StringTable('081604b0', [{entries}])]), VarFileInfo([VarStruct('Translation', [2070,1200])])])",
        encoding="utf-8")
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed", "--noupx",
               "--name", "SlabsEC2", "--version-file", str(metadata),
               "--collect-data", "reportlab", "--hidden-import", "openpyxl", "--hidden-import", "xlsxwriter"]
    assets = ROOT / "slabsec2/assets"
    if (assets / "slabsec2.png").is_file():
        from PIL import Image
        with Image.open(assets / "slabsec2.png") as original:
            icon = original.convert("RGBA")
            icon.save(assets / "slabsec2.ico", sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
        command += ["--icon", str(assets / "slabsec2.ico"), "--add-data", f"{assets}:slabsec2/assets"]
    subprocess.run(command + ["main.py"], cwd=ROOT, check=True)
    environment = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True)
    info = {"application": "SlabsEC2", "version": version, "python": sys.version,
            "platform": platform.platform(), "architecture": platform.machine(),
            "dependencies": environment.splitlines()}
    (ROOT / "dist/build-info.json").write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
