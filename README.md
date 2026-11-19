# SEFAZ-MT LAB — Experimento independente

## Coleta atual de NF-e

Para executar a coleta automatizada de entrada e saída da empresa de exemplo, com o A1
instalado no Windows e o Chrome disponível:

```powershell
cd C:\Users\Matheus\Desktop\sefaz-mt-lab-v3\sefaz-mt-lab-v3
.\.venv\Scripts\python.exe coletar_nfe.py --cnpj 12345678000199 --ie 123456789 --inicio 01/10/2026 --fim 31/10/2026 --tipo ambas --tentativas-login 15 --tentativas-certificado 6
```

O Cloudflare pode liberar o acesso automaticamente; caso apresente um desafio
que exija uma pessoa, a rotina aguarda até 120 segundos sem solucioná-lo.
Por padrão, o Chrome usa um perfil novo isolado por execução em `saida/perfis/`.
Para reutilizar um perfil existente, informe `--perfil` com seu caminho dentro
de `saida/perfis/`. O perfil anteriormente usado não é removido.
Os relatórios exportados nesta execução e os CSVs de chaves ficam em
`saida/coletas/<CNPJ>/<AAAA-MM>/<id>/`. O comando não consulta o Meu Danfe.
As tentativas acima são limitadas para que uma empresa indisponível não bloqueie
indefinidamente a execução. O comportamento real depende do portal.

## Coleta de NF-e em lote

Crie um CSV UTF-8 com cabeçalho `cnpj;ie` e uma empresa por linha. O arquivo
`empresas_exemplo.csv` contém apenas a empresa de exemplo. Preserve os identificadores
como texto, inclusive zeros à esquerda. Cada empresa deve ter seu A1 instalado
no Windows; o seletor atual exige um certificado único com o CNPJ da empresa.
O uso de um único certificado de procurador para várias empresas não foi validado.

```powershell
.\.venv\Scripts\python.exe lote_nfe.py --empresas empresas.csv --inicio 01/09/2026 --fim 30/09/2026
```

O lote é sequencial, coleta somente NF-e recebidas e emitidas e não chama o
Meu Danfe. O progresso é salvo em `saida/lotes/`; os arquivos fiscais ficam
em `saida/coletas/`. Repita o mesmo comando com a mesma lista, ordem e período
para pular empresas concluídas e tentar novamente falhas. Uma lista ou período
diferentes formam outro lote, que não reutiliza o checkpoint anterior.
Após interrupção abrupta, uma empresa marcada `INTERROMPIDO_VERIFICAR` não é
repetida automaticamente; verifique o processo e a coleta antes de retomá-la.
Um desafio de segurança pode exigir validação humana no navegador. Ainda não
foi comprovada uma execução com múltiplas empresas reais.

> **v4 (13/11/2026):** A coleta de chaves é uma ponte para recuperar XMLs completos via Meu Danfe API v2. O módulo `meu_danfe.py` usa os endpoints confirmados no Swagger oficial, limitado a uma chave por execução. Busca potencialmente cobrada exige `--autorizar-consulta-paga`. A validação do XML é estrutural e não verifica criptograficamente a assinatura. Ver `PRD_AUTOMACAO.md`, `PROMPT_CODEX.md`.

> **v2 (12/11/2026):** Exemplos reais analisados; suporte offline a chaves NF-e modelo 55 e NFC-e modelo 65 mascaradas. Ver `PRD_AUTOMACAO.md` e `PROMPT_CODEX.md`. A navegação completa ainda precisa de mapeamento de DOM no computador do operador.

Experimento para **testar se o Google Chrome controlado pelo DrissionPage abre a SEFAZ-MT**, registrar eventuais bloqueios/desafios, e, **se houver acesso autorizado**, baixar uma planilha Excel de NF-e emitidas/recebidas e extrair chaves de 44 dígitos válidas (módulo 11).

**Não é integrado à Central 68 nem ao Baixador Morpho.** Não inclui soluções para quebrar CAPTCHA, automatizar desafios Cloudflare ou contornar bloqueios de segurança. Não utiliza API privada da SEFAZ nem armazena certificados. O login com A1 instalado no Windows pode ser automatizado com os parâmetros abaixo; a navegação até a consulta e a exportação ainda dependem do mapeamento do portal para o perfil Contribuinte MT.

## Pré-requisitos

- Windows 10/11, Chrome instalado e Python 3.10 ou superior.
- Acesso legítimo ao Sefaz Digital/Acesso Web com credenciais/certificado e procuração, quando exigidos.
- Abra um PowerShell na pasta do projeto.

## Instalação (PowerShell)

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Se o PowerShell bloquear a ativação do ambiente virtual, use `\.venv\Scripts\python.exe` em vez de `python` sem ativar.

## Teste 1 — O Chrome automatizado abre a SEFAZ?

```powershell
python main.py --etapa acesso
```

Por padrão, o endereço inicial é:
`https://www.sefaz.mt.gov.br/acesso/pages/login/login.xhtml`

**Para reproduzir precisamente a falha do seu robô, use a URL exata que ele abre:**

```powershell
python main.py --etapa acesso --url "https://www.sefaz.mt.gov.br/acesso/pages/login/login.xhtml"
```

O programa abre um Chrome controlado por DrissionPage, aguarda o carregamento e salva:

- `saida/01_acesso_inicial.json` — status estimado, título e URL final;
- `saida/01_acesso_inicial.png` — captura de tela.

Resultados possíveis: `BLOQUEIO_DETECTADO`, `DESAFIO_DETECTADO`, `PAGINA_CARREGADA_SEM_DESAFIO_EVIDENTE`, `PAGINA_NAO_CARREGADA`. A detecção é heurística: não comprova o sucesso de autenticação e pode não reconhecer alguns desafios.

## Teste 2 — Capturar a planilha, se o acesso funcionar

Para isolar a etapa de autenticação com o A1 instalado no Windows, execute no PowerShell, substituindo os valores de exemplo pelos dados da empresa autorizada:

```powershell
python main.py --etapa login --login-automatico --cnpj 00000000000000 --ie 000000000 --perfil-temporario
```

O script só confirma sucesso se a URL autenticada do Acesso Web for exibida. Se o portal retornar ao formulário, a tentativa termina com falha e não coleta chaves. O seletor nativo do Chrome é confirmado por `certificado_chrome.ps1` apenas quando encontra exatamente um certificado com o CNPJ pedido. Nenhum PFX ou senha é lido pela rotina.

O portal pode permanecer no mesmo formulário após um envio sem apresentar erro. Nesse caso, a rotina faz no máximo 8 envios com intervalo de 5 segundos e interrompe ao receber uma mensagem de erro ou desafio de segurança. Para reduzir o limite, use `--tentativas-login 3`. O diagnóstico de falha de login registra JSON sem captura de tela do campo de IE.

```powershell
python main.py --etapa planilha
```

1. O script abre o navegador e registra o resultado inicial.
2. Se o Cloudflare exigir uma etapa humana, resolva-a **pessoalmente**, caso o portal permita; o programa não a automatiza.
3. Entre no portal com a autorização do contribuinte/contabilista.
4. Acesse **Nota Fiscal Eletrônica → Consulta de NF-e Emitida/Recebida**, selecione a empresa/período e consulte.
5. Volte ao PowerShell e pressione ENTER.
6. Clique em **Exportar para Excel** no Chrome. O programa monitora por até 120 segundos somente uma pasta nova e vazia criada para a execução dentro de `saida/downloads/`.
7. Ao encontrar uma exportação nova `.xlsx`, `.xls`, `.csv`, `.txt` ou `.zip` nessa pasta, extrai as chaves válidas sem duplicações e salva `chaves_extraidas.csv` ao lado do arquivo baixado. Arquivos preexistentes e a pasta Downloads do Windows não são lidos por essa rotina.

Após você identificar o seletor real do botão de exportação, pode testar um clique automatizado *apenas depois de chegar à tela de resultados*:

```powershell
python main.py --etapa planilha --seletor-exportacao "text:Exportar para Excel"
```

**Atenção:** esse seletor é ilustrativo; o texto/botão pode ser diferente no portal.

## Testes locais da extração

```powershell
python -m unittest discover -s tests -v
```

O teste usa uma chave sintética fictícia, nunca uma chave real.

## Coleta automatizada de NF-e modelo 55

Após instalar o A1 da empresa no repositório pessoal de certificados do Windows, informe o CNPJ, a IE e o período. Exemplo para um mês completo no PowerShell:

```powershell
$cnpj = Read-Host 'CNPJ (14 dígitos)'
$ie = Read-Host 'IE de MT (9 dígitos)'
.\.venv\Scripts\python.exe coletar_nfe.py --cnpj $cnpj --ie $ie --inicio 01/10/2026 --fim 31/10/2026 --tipo ambas
```

`--tipo` aceita `recebidas`, `emitidas` ou `ambas`. A rotina seleciona o A1 instalado, faz o login como Contribuinte MT, abre o item real **Consulta de NF-e Emitida/Recebida**, preenche o período, preserva os filtros de UF e situação como `Todas`, consulta e exporta o XLS. A seleção do certificado e o envio do login têm limites de tentativas; desafios de segurança interrompem a execução.

Cada execução cria uma pasta em `saida/coletas/<CNPJ>/<AAAA-MM>/<id>/`. Dentro dela, `recebidas/` e `emitidas/` guardam o XLS original, `chaves_extraidas.csv` e `manifesto.json`. `relatorio.json` indica quais tipos terminaram ou falharam. A validação exige chave modelo 55 com DV correto, emitente coerente com a chave, empresa correta na operação, datas dentro do período e igualdade entre a coluna fiscal e o extrator genérico. Nenhum arquivo da pasta Downloads do Windows é usado. Esta etapa apenas coleta chaves; não chama a API do Meu Danfe.

## Como interpretar

| Resultado | O que significa | Próximo passo |
|---|---|---|
| Bloqueio/desafio ao abrir | O robô não passou da camada inicial | Compare com Chrome aberto manualmente na mesma rede; registre as evidências e solicite orientação/autorização à SEFAZ |
| Página carregou sem desafio evidente | Portal carregou, mas ainda não há prova de login | Executar teste 2 |
| Login autorizado + exportação ocorreu | Acesso e obtenção de dados comprovados localmente | Levantar seletores da consulta e automatizar operações permitidas |
| Arquivo baixou, mas sem chaves | Exportação pode não conter coluna textual com chave | Inspecionar cabeçalhos/planilha e seus formatos |

## Observações importantes

- Não salve credenciais, senha de certificado ou arquivos PFX nesta pasta.
- `saida/` e `perfil_chrome/` podem conter dados fiscais sensíveis e não são enviados automaticamente a nenhum servidor. Não compartilhe capturas, planilhas ou perfil sem anonimizar.
- O portal pode mudar sem aviso. O projeto **não** garante sucesso de acesso nem dispensa autorização da SEFAZ.
- Caso o portal altere o perfil ou redirecione ao Sefaz Digital, substitua a URL inicial pela **URL exata** em uso na sua operação.
- O Excel armazena números com precisão limitada; a chave de 44 dígitos deve ser exportada como **texto**. O extrator rejeita chaves que não passem no dígito verificador, mas um dígito verificador válido não comprova autenticidade de NF-e.


## Prova controlada de XML (v4)

Contrato confirmado em [documentação oficial v2](https://meudanfe.com.br/doc/v2.php): `GET /fd/get/xml/{Chave-Acesso}` faz download gratuito de NF-e já adicionada à conta; `PUT /fd/add/{Chave-Acesso}` solicita busca e pode cobrar R$ 0,03. A resposta do GET é JSON com `type=NFE`, `format=XML` e `data` contendo o texto XML. O módulo sempre tenta o GET primeiro. Um 404 sem autorização explícita termina em `AGUARDANDO_APROVACAO_CUSTO`.

Crie `.env` local na pasta do projeto com `MEUDANFE_API_KEY=sua_chave`. `.env` e `saida/` estão no `.gitignore`. Depois de uma exportação nova feita no navegador pela rotina acima, para testar **uma única chave** sem permitir busca cobrada, use o caminho da planilha exibido nessa mesma execução:

```powershell
python meu_danfe.py --planilha "CAMINHO_DA_EXPORTACAO_DESTA_EXECUCAO" --tipo emitidas
```

O comando escolhe a primeira chave modelo 55 com dígito verificador válido; no tipo `emitidas`, usa o CNPJ da chave para organizar o arquivo. Para `recebidas`, informe `--cnpj-empresa` com o CNPJ da empresa atendida. Para uma chave específica, use `--chave CHAVE_DE_44_DIGITOS` no lugar de `--planilha`.
Para escolher outra chave distinta da planilha sem expô-la na linha de comando, use `--indice-chave 1` (índices iniciam em 0). Cada execução continua limitada a uma chave.

Somente após concordar com uma busca que pode cobrar R$ 0,03, execute o mesmo comando com `--autorizar-consulta-paga`. O histórico local em `saida/xmls/historico/` impede repetir automaticamente um PUT cujo resultado ficou incerto. A saída não imprime a chave nem dados fiscais.

A ausência de `Signature` não bloqueia mais a conferência dos dados. `XML_VALIDADO_ESTRUTURALMENTE` indica que as verificações de chave, modelo, emitente, destinatário, itens e protocolo passaram no formato esperado pelo validador; `XML_DADOS_FISCAIS_CONFERIDOS` indica que essas verificações passaram, mas o XML veio sem assinatura ou com itens representados por `<nItem>` em vez de `det/@nItem`. O arquivo é preservado byte a byte em `saida/xmls/<CNPJ>/<AAAA>/<MM>/nfe_<tipo>_dados_meudanfe/`. Um segundo processamento retorna `JA_EXISTEM_DADOS_FISCAIS` sem consultar a API. Nenhum desses estados atesta autenticidade criptográfica, conformidade XSD ou prontidão para importar no Domínio.

**Resultado das provas reais (13/11/2026):** três chaves distintas receberam status `OK` na busca via API v2 e retornaram `nfeProc` sem `Signature`; as respostas originais dessas provas permaneceram em `saida/xmls/quarentena/` e não foram reprocessadas. Uma quarta chave, desta vez da exportação automática da SEFAZ-MT para a empresa de exemplo, foi consultada uma vez e baixada novamente sem nova busca paga. Chave, modelo 55, emitente, itens e protocolo passaram na conferência; o arquivo foi salvo como `XML_DADOS_FISCAIS_CONFERIDOS` porque a resposta não tem assinatura e representa `nItem` como elemento. A cobrança efetiva não foi verificada. Nenhuma consulta em lote foi executada.

Na terceira prova, a mesma chave foi comparada com um XML assinado fornecido pelo operador. A assinatura desse arquivo passou na verificação criptográfica básica com `.NET SignedXml.CheckSignature()`, usando a chave pública incluída no próprio XML; isso confirma correspondência criptográfica do conteúdo, mas não confirma que o certificado pertence a um emissor confiável. A cadeia de confiança do certificado não foi verificada. Os valores dos campos fiscais e dos itens coincidiram com o retorno do Meu Danfe, mas o retorno da API omitiu a assinatura, `protNFe/@versao`, `infProt/tpAmb` e `infProt/verAplic`; trouxe `det/nItem` como elemento no lugar do atributo `det/@nItem` e adicionou elementos `infNFe/Id` e `nfeProc/versao`. A ordem dos elementos também mudou: o original inicia por `NFe`, enquanto o retorno inicia por `protNFe`; dentro de `infNFe`, o original inicia por `ide`, enquanto o retorno inicia por `infAdic`. A validação por XSD ainda não foi executada.

Para inspeção offline de um XML que já possua, execute:

```powershell
python validar_xml.py caminho\nota.xml --chave CHAVE_DE_44_DIGITOS
```

A saída confirma **somente coerência estrutural** de `nfeProc` e protocolo; não valida criptograficamente a assinatura nem prova autenticidade.

## Relatório por produto dos XMLs recuperados

`relatorio_nfe.py` gera uma planilha `.xlsx` com as 54 colunas do relatório de NF-e fornecido como referência. Cada item de uma NF-e ocupa uma linha; campos ausentes no XML ficam vazios. A planilha de referência foi usada apenas para definir colunas e apresentação, nunca como fonte de chaves ou dados das notas. Os XMLs são lidos de `saida/xmls/`, incluindo os retornos transformados do Meu Danfe que passaram na conferência de chave, empresa, modelo 55, itens e protocolo. O arquivo original do XML permanece intacto.

Após cada recuperação bem-sucedida por `meu_danfe.py`, a planilha da empresa e do mês é atualizada automaticamente em `saida/relatorios/<CNPJ>/<AAAA-MM>/RelatorioNFe_XML.xlsx`. É possível escolher outro destino com `--relatorio-xlsx`. Para reconstruir o relatório a partir dos XMLs já salvos, sem consultar a API, use:

```powershell
.\.venv\Scripts\python.exe relatorio_nfe.py --xml-dir "saida\xmls\12345678000199\2026\10" --cnpj-empresa 12345678000199 --saida "saida\relatorios\12345678000199\2026-10\RelatorioNFe_XML.xlsx"
```

No estado atual, há uma NF-e emitida recuperada para essa empresa, com quatro itens; o relatório contém quatro linhas de dados. As demais 90 chaves da coleta ainda não têm XML recuperado. A planilha de NFS-e fornecida como referência tem outro esquema e será tratada pelo módulo próprio de serviços quando houver XML de NFS-e obtido da ADN.

## Relatório mensal com seis abas

`relatorio_mensal.py` cria, nesta ordem, `NF-e entrada`, `NF-e saída`, `NFS-e entrada`, `NFS-e saída`, `CT-e entrada` e `CT-e saída`. As abas de NF-e têm uma linha por item dos XMLs recuperados. As de NFS-e e CT-e mostram explicitamente que a coleta de XML ainda não foi confirmada; não são preenchidas com as planilhas de exemplo. O comando do Meu Danfe atualiza este relatório mensal automaticamente após cada XML aceito.

```powershell
.\.venv\Scripts\python.exe relatorio_mensal.py --cnpj 12345678000199 --competencia 2026-10 --coleta "saida\coletas\12345678000199\2026-10\20261113_172517_054012_0995d2b5" --saida "saida\relatorios\12345678000199\2026-10\RelatorioMensal.xlsx"
```

O login da SEFAZ-MT aguarda até 10 segundos depois de cada seleção do certificado e de cada envio do formulário; se a tela permanecer no mesmo estado sem erro, repete o clique até o limite configurado. A consulta de NF-e repete o envio apenas quando o resultado não aparece. A exportação só é repetida se não existir arquivo concluído nem download em andamento. Desafios de segurança e erros explícitos interrompem a rotina. O diagnóstico de CT-e foi iniciado em `diagnosticar_cte.py`, mas a inspeção do menu ainda não foi confirmada no portal real; nenhum XPath ou seletor de CT-e foi presumido. Para NFS-e, a fonte planejada continua sendo exclusivamente a API de distribuição do ADN. Nenhum XML de CT-e ou NFS-e foi coletado nesta versão.

