# Distribuição para Windows

## Utilização sem Python

Descarregar o ficheiro `.exe` na secção [Releases](https://github.com/lutondatomalela/SlabsEC2/releases). Guardar numa pasta local e abrir. Não requer instalação nem permissões de administrador.

Destino: Windows 10/11 de 64 bits (x64). O executável inclui o interpretador e as bibliotecas utilizadas pela aplicação. A primeira abertura pode demorar alguns segundos. Os dados de projeto e os relatórios continuam a ser guardados nos locais escolhidos pelo utilizador.

O executável não tem assinatura digital. Confirmar a origem do ficheiro e o SHA-256 publicado, sem desativar os mecanismos de segurança do sistema.

## Verificações e diagnóstico

As opções de validação também funcionam no executável. Em PowerShell, utilizar `Start-Process -Wait` para aguardar o fim de uma aplicação sem consola:

```powershell
Start-Process -FilePath .\SlabsEC2-v2.16.0-rc1-windows-x64.exe -ArgumentList '--installation-check --output verificacao.txt' -Wait
Get-Content .\verificacao.txt -Encoding UTF8
```

Estão igualmente disponíveis `--self-test`, `--validation-suite`, `--manual-validation`, `--audit` e `--version`. O argumento `--output` guarda o resultado em UTF-8. Uma verificação que falhe devolve código 1; argumentos inválidos devolvem código 2.

Erros não tratados são registados em `%LOCALAPPDATA%\SlabsEC2\logs\SlabsEC2.log`. Se essa pasta não permitir escrita, é utilizada a pasta temporária do utilizador.

## Reproduzir a compilação

Em Windows x64, com Python 3.12:

```powershell
py -3.12 -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv-build\Scripts\python.exe scripts/build_windows.py
.\.venv-build\Scripts\python.exe scripts/verify_windows.py
```

A pasta `dist/` recebe o executável, os resultados de validação, a identificação do ambiente e os hashes SHA-256. As versões diretas estão fixadas em `requirements-build.txt`; o conjunto efetivamente instalado, incluindo dependências transitivas, é registado em `build-info.json`.

O fluxo `Windows executable`, em GitHub Actions, executa a mesma sequência. Uma publicação só é criada depois de todos os testes passarem. Versões já publicadas são preservadas; para distribuir alterações posteriores deve ser atribuída uma nova versão.

Referências de compilação: [PyInstaller](https://pyinstaller.org/en/stable/usage.html), [recursos incluídos no executável](https://pyinstaller.org/en/stable/runtime-information.html) e [publicações com GitHub CLI](https://cli.github.com/manual/gh_release_create).
