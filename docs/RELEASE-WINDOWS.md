## Executável para Windows

Distribuição autónoma da versão **v2.16.0-rc1** para Windows de 64 bits. Inclui Python e as dependências necessárias ao funcionamento do SlabsEC2.

### Utilização

1. Descarregar `SlabsEC2-v2.16.0-rc1-windows-x64.exe` nos ficheiros desta versão.
2. Guardar numa pasta local e abrir o executável. Não é necessário instalar Python nem executar como administrador.
3. Importar os dados, definir as combinações e os parâmetros da laje e efetuar o cálculo.

A primeira abertura pode demorar alguns segundos, enquanto os componentes são extraídos para a pasta temporária do utilizador. O executável não tem assinatura digital.

### Ajustes desta distribuição

- Arranque independente da pasta de trabalho e funcionamento sem consola.
- Registo de erros em `%LOCALAPPDATA%\SlabsEC2\logs\SlabsEC2.log`.
- Verificações automáticas executadas no próprio binário: 110 autotestes, 45 verificações técnicas, 138 comparações numéricas e 9114 controlos determinísticos.
- Verificação adicional de abertura da interface, importação CSV/XLSX, cálculo ELU/ELS e exportação de Excel, memória de cálculo e auditoria PDF, com dados sintéticos e caminhos com espaços e acentos.

O motor de cálculo da v2.16.0-rc1 mantém-se inalterado. A compilação e os testes são efetuados num ambiente Windows Server 2022 x64 do GitHub Actions; a distribuição destina-se a Windows 10/11 x64.

`SHA256SUMS.txt` permite verificar a integridade dos ficheiros. `build-info.json` identifica o código-fonte, o ambiente e as dependências; `VALIDATION-WINDOWS.txt` contém os resultados dos testes.

Mantém-se o estado **Release Candidate** e o âmbito de cálculo descrito no README. Os testes não constituem certificação externa.
