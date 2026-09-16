"""Testar o binário fora do repositório, incluindo espaços e acentos no caminho."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    version = runpy.run_path(str(ROOT / "slabsec2/version.py"))["VERSION"]
    evidence = []
    modes = [("--self-test", "110 testes concluídos: OK"),
             ("--validation-suite", "45/45"), ("--manual-validation", "138/138"),
             ("--audit", "9114/9114"), ("--installation-check", "Memória de cálculo e auditoria PDF: OK")]
    with tempfile.TemporaryDirectory(prefix="SlabsEC2 teste autónomo ") as tmp:
        folder = Path(tmp)
        exe = folder / "SlabsEC2.exe"
        shutil.copy2(ROOT / "dist/SlabsEC2.exe", exe)
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        for index, (mode, expected) in enumerate(modes):
            output = folder / f"Verificação {index}.txt"
            process = subprocess.run([str(exe), mode, "--output", str(output)], cwd=folder, env=env, timeout=240)
            report = output.read_text(encoding="utf-8") if output.exists() else "Sem relatório"
            if process.returncode != 0 or expected not in report:
                raise RuntimeError(f"{mode}: código {process.returncode}\n{report}")
            if mode == "--installation-check" and "Executável autónomo: True" not in report:
                raise RuntimeError("A verificação não foi executada no binário autónomo")
            evidence.append(report)
            print(f"{mode}: OK", flush=True)
        invalid = subprocess.run([str(exe), "--opcao-invalida"], cwd=folder, env=env, timeout=60)
        if invalid.returncode != 2:
            raise RuntimeError("Argumentos inválidos não devolveram o código de erro esperado")
    dist = ROOT / "dist"
    target = dist / f"SlabsEC2-v{version}-windows-x64.exe"
    (dist / "SlabsEC2.exe").replace(target)
    (dist / "VALIDATION-WINDOWS.txt").write_text("\n\n".join(evidence), encoding="utf-8")
    info_path = dist / "build-info.json"
    info = json.loads(info_path.read_text(encoding="utf-8"))
    info.update({"commit": os.environ.get("GITHUB_SHA", "local"), "tests_passed": [x[0] for x in modes],
                 "invalid_arguments_exit_code": 2})
    info_path.write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    assets = [target, info_path, dist / "VALIDATION-WINDOWS.txt"]
    checksum = "".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in assets)
    (dist / "SHA256SUMS.txt").write_text(checksum, encoding="utf-8")
    print(checksum)


if __name__ == "__main__":
    main()
