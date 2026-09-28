# Controle de Ponto

Aplicação web local para importar formulários `.xls`/`.xlsx`, identificar funcionários com horários reais, conferir fichas e gerar PDFs.

## Executável para Windows

Use `ControleDePonto-Miranda-Revisado.exe` para abrir a versão portátil; não é necessário instalar Python nem as bibliotecas do sistema. O programa abre a interface no navegador e processa as planilhas localmente.

### Atualizações automáticas

Ao abrir o executável, o aplicativo consulta apenas a API pública de releases do GitHub. Se houver uma versão mais nova, baixa o executável, confere o SHA-256 publicado pelo GitHub e o substitui, reiniciando em seguida. A consulta não envia planilhas, marcações nem dados de funcionários. Sem internet, ou se a consulta falhar, o aplicativo inicia a versão instalada normalmente.

Para publicar uma versão, atualize `APP_VERSION` em `version.py` somente para builds locais (os builds oficiais recebem a versão pela tag), crie e envie uma tag no formato `vMAJOR.MINOR.PATCH` — por exemplo, `v1.0.1`. A ação em `.github/workflows/release.yml` compila o executável no Windows e cria um GitHub Release com o instalador portátil. Não inclua planilhas reais, relatórios ou dados pessoais no repositório.

O executável que já está em uso precisa ser trocado uma última vez pela versão que contém o atualizador. A partir dessa versão, as versões posteriores são obtidas automaticamente.

## Como abrir

1. Dê dois cliques em `ControleDePonto-Miranda-Revisado.exe`.
2. Aguarde o navegador abrir em `http://127.0.0.1:8766`.
3. Arraste a planilha mensal para a área de importação.

Não é necessário instalar Python. A conexão com a internet é usada somente para verificar atualizações. A planilha é processada neste computador e não é enviada ao GitHub nem a outro serviço externo.

`INICIAR SISTEMA.bat` é uma alternativa para desenvolvimento a partir do código-fonte e requer Python e acesso à internet para instalar bibliotecas.

## Funções

- Pesquisa e filtro por departamento.
- Diagnóstico de funcionários ignorados por não possuírem horários.
- Visualização da ficha individual.
- Revisão de marcações incompletas e intervalos de almoço acima de 1h30 antes da geração.
- PDF individual, ZIP de selecionados e PDF único para impressão, com nomes organizados por funcionário e período.
- Rascunho automático das edições no armazenamento local do navegador; para recuperar após reabrir, reimporte a mesma planilha e abra a ficha. As cópias podem ser apagadas pela própria tela.
- Exclusão automática de funcionários sem qualquer marcação real.

Cada planilha importada é removida da pasta temporária após a leitura. Os dados ficam na memória do programa durante a sessão; os rascunhos de horários permanecem somente no perfil local do navegador até serem apagados. Ao fechar o aplicativo, a memória da sessão é encerrada.

## Ícone do executável Windows

O recurso `assets/grupo-miranda.ico` é usado no build do executável e contém os tamanhos de ícone padrão do Windows.

## Parser no terminal

```powershell
python -m attendance_parser "C:\caminho\Formulário.xls" --json diagnostico.json
```

## Testes

```powershell
python -m unittest discover -s tests -v
```

O arquivo de origem nunca é alterado. O parser considera somente células pertencentes às colunas de horário identificadas pelos cabeçalhos da tabela diária.
