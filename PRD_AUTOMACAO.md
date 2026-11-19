# PRD — SEFAZ-MT LAB | Coleta de chaves e recuperação de XMLs

## Objetivo
**Objetivo final: recuperar XMLs fiscais completos e válidos para posterior importação ao Domínio.** A coleta das chaves é uma etapa intermediária, não o entregável final. A integração efetiva com o Domínio permanece fora do escopo desta PoC até que a recuperação e a validação do XML tenham sido demonstradas.

Automatizar, em um **projeto isolado da Central 68**, o fluxo que o operador demonstrou no vídeo da SEFAZ-MT: login autorizado com certificado digital no Acesso Web/PAC; escolha de contribuinte com IE; consulta de NF-e como **Emissor** e **Destinatário**; consulta de **NFC-e Emitidas** por Mês/Ano; exportação das planilhas `.xls`; validação e armazenamento das chaves de 44 dígitos.

Não integrar com Central 68 nem incorporar o Baixador Morpho. Nesta versão, preparar os XMLs para possível importação futura no Domínio, sem implementar envio automático. Não criar funções para empresas sem IE. Não incluir CAPTCHA solving, fingerprint spoofing, proxies de evasão, bypass Cloudflare ou execução automática de desafio humano. Se houver desafio, sinalizar e permitir conclusão manual autorizada.

## Evidências fornecidas
- Vídeo `2026-11-12 09-32-07.mp4` (123 s): navegação real pelo portal SEFAZ-MT; fluxos emitente, destinatário e NFC-e; acesso já autenticado.
- `ConsultaNFeEmitidasRecebidas1794491585717.xls`: NF-e emitidas; 6 chaves modelo 55, sem máscara, todas autorizadas.
- `ConsultaNFeEmitidasRecebidas1794491602480.xls`: NF-e recebidas; 65 chaves modelo 55, sem máscara; 63 autorizadas e 2 canceladas.
- `Planilha_1794491541940.xls`: NFC-e emitidas; 1.356 chaves modelo 65, **com máscara/pontuação**; 1.297 autorizadas, 58 autorizadas fora de prazo e 1 cancelada.
- Total: **1.427 chaves distintas, com 44 dígitos e dígito verificador válido**.
- As planilhas anexadas referem-se a agosto de 2026; o período digitado no vídeo exemplifica outubro de 2026. Não presumir que são a mesma execução.
- **Os três arquivos são Excel binário OLE/BIFF `.xls`, não `.xlsx` nem HTML com extensão `.xls`.**

## Navegação mapeada visualmente
### NF-e (modelo 55)
1. Tela de acesso já autenticada: `https://www.sefaz.mt.gov.br/acesso/pages/paginainicial.xhtml` (rota visível no vídeo; o fluxo antes da autenticação varia).
2. Menu lateral **Nota Fiscal Eletrônica - NF-e** > **Consultas** > **Consulta de NF-e Emitida/Recebida**.
3. Tela **Dados para Consulta** identifica a empresa logada/selecionada e a IE.
4. Preencher **Data Inicial** e **Data Final** com `DD/MM/AAAA`.
5. Em **Tipo de Consulta**, escolher **Emissor** para NF-e emitidas ou **Destinatário** para recebidas.
6. Preservar filtros configuráveis **UF para qual o Emissor emitiu NF-e** (no exemplo `Todas`) e **Situação NF-e** (`Todas`), para não ignorar canceladas.
7. Clicar **Consultar**; validar que o painel **Resultado da Consulta** foi exibido. Na lista, localizar o botão **Exportar para Excel**. A lista exibida na tela tem uma coluna **Chave de Acesso**.
8. Esperar o download completar sem sobrescrever arquivos de outra consulta.

### NFC-e (modelo 65)
1. Menu lateral **Nota Fiscal de Consumidor Eletrônica** > **Consulta de NFC-e(s) Emitidas**.
2. Tela **Consultar NFC-e Emitidas**, preencher **Mês/Ano** em `MM/AAAA` (ex.: `10/2026`).
3. Clicar **CONSULTAR**; a página pode demorar e indicar `Aguarde... Carregando`.
4. Verificar se o sistema entrega um arquivo, resultado ou mensagem de ausência de notas; guardar evidência e baixar a planilha produzida, quando houver.
5. Não reaproveitar seletores/fluxo de NF-e: este formulário é diferente.

**A gravação não fornece seletores DOM confiáveis; o Codex precisa inspecioná-los no Chrome real do usuário.** Não inventar IDs/XPath a partir da aparência do vídeo. Observar se o conteúdo está em `iframe`, aba, janela ou componente dinâmico.

## Estrutura das planilhas (validada em amostras)
- Todas têm uma aba e **cabeçalho na linha 7 (índice Python 6)**, registros a partir da linha 8 (índice 7), **chave na coluna D** (índice 3), porém localizar primeiro pelo cabeçalho `CHAVE DE ACESSO` para resistir a mudanças.
- NF-e: aba `ConsultaNFe`; colunas A-D = Data Emissão, Série, Número Nota Fiscal, Chave de Acesso. Coluna I = Situação; demais campos de emitente e destinatário, UF, valores e protocolo.
- NFC-e: aba `ConsultaNfe`; colunas A-D = Data Emissão, Série, NNF, Chave de Acesso. Coluna I = Situação. A chave vem visualmente formatada com pontos, hífens e barra e precisa ter a pontuação removida antes da validação.
- Detectar tipo pelo `chave[20:22]` (`55` ou `65`), validar 44 dígitos e DV módulo 11, descartar entradas inválidas e preservar chaves como strings/texto.
- Preservar canceladas e outras situações no registro de saída; não filtrar silenciosamente por autorização.

## Requisitos funcionais
R1. CLI `python main.py --etapa acesso` permanece funcional; o teste de acesso do DrissionPage **já foi validado pelo operador**, mas sem garantia universal contra desafios futuros.
R2. Adicionar comandos `--etapa nfe-emitidas`, `--etapa nfe-recebidas`, `--etapa nfce-emitidas` e, futuramente, `--etapa todas`. Não implementar fluxo com seletores fictícios: usar modo assistido até DOM verificado.
R3. Registrar empresa/IE, competência, tipo, período, resultado, status, nome do arquivo, contagem de linhas, chaves válidas, canceladas e erros.
R4. Completar download `.xls` por evento nativo ou espera de arquivo estável e extensão temporária removida; timeout parametrizável; não confiar exclusivamente em clique bem-sucedido.
R5. Organizar armazenamento por IE/CNPJ autorizados + competência + tipo, com arquivo original preservado; nunca cometer PFX, senhas, cookies, dados reais ou screenshots de empresa no Git.
R6. Extrator independente, testável sem navegador, com validação tanto das chaves em texto puro quanto mascaradas; oferecer CSV com `chave_acesso`, `modelo`, `situacao`, `data_emissao`, `numero_nota`, `empresa_ie`, `tipo_consulta`, `competencia`, `arquivo_origem` quando essas informações estiverem disponíveis.
R7. Deduplicar por chave de 44 dígitos **dentro da empresa**, preservando o arquivo original e os registros de origem; respeitar chaves de mesma NF-e encontradas em consultas diferentes.
R8. Identificar portal autenticado/perfil ativo; quando usar várias IEs, não assumir troca de contribuinte por mera edição do CNPJ; primeiro investigar o fluxo autorizado de mudança de empresa.
R9. Se um desafio Cloudflare/CAPTCHA reaparecer, **parar e sinalizar**; nenhuma tentativa de contornar verificações.
R10. Falha de exportação, falta de notas, sessão expirada e filtro incompatível devem produzir estados diferentes; não transformar falha em sucesso.

## Estratégia de implementação
**Fase 1 — Extractor e teste offline:** usar as três planilhas reais como *fixtures privadas* colocadas localmente em `referencias/` (gitignored); os testes públicos usam apenas chaves inventadas com DV válido. Conferir 6 + 65 + 1356 e 0 inválidas nos exemplos.

**Fase 2 — Mapeamento DOM local:** com `agent-desktop` (se instalado) ou inspeção via DrissionPage, identificar os elementos reais de menu, inputs, radio buttons, combos, submit e exportação. Registrar em `docs/mapeamento_dom.md`, com evidências não sensíveis. Não mudar `main.py` por tentativa e erro sem medir resultado.

**Fase 3 — Primeiro fluxo ponta a ponta:** automatizar NF-e recebidas de **uma única IE** e período curto, com login autorizado, consulta, download, extração, verificações e logs. Só declarar sucesso se a saída real tiver chaves válidas e arquivo presente (ou ausência de notas explicitamente indicada pelo portal).

**Fase 4 — Demais fluxos:** emitir NF-e e consultar NFC-e mensal; observar fluxos e download distintos.

**Fase 5 — Robustez:** repetição controlada, tempos de espera por condição, reprocessamento manual de falhas, logs sem dados sensíveis, verificação de consistência, múltiplas competências e, somente após validar, múltiplas IEs.

## Critérios de aceite
A. Execução local em Windows com Chrome + DrissionPage, independente da Central 68.
B. Teste offline reconhece as 1.427 chaves disponibilizadas e 3 relatórios, sem confundir modelos 55/65, preservando situações (inclusive canceladas).
C. Ao finalizar uma rotina, o arquivo original existe, tem tamanho estável, cabeçalho reconhecido, chaves extraídas, saída CSV e relatório JSON/CSV de execução.
D. Não hardcodar CNPJ, IE, certificado, datas, nomes da gravação ou XPaths não verificados.
E. Não incluir dados fiscais verdadeiros nos logs, testes versionados, mensagens de erro ou arquivos públicos.
F. Se o portal alterar interface/bloquear a automação, o robô interrompe com status útil, sem tentativa de bypass.

## Riscos/pendências
- No vídeo, o portal está **logado em um contribuinte**. A troca automática entre diversas empresas não está demonstrada; investigar antes de prometer rotina em lote.
- Acesso e comportamento do Cloudflare podem variar entre execuções.
- Consulta da SEFAZ mostra chaves e metadados, mas não garante disponibilização de XML completo. Esta fase é apenas **coleta de chaves**.
- Os `.xls` são BIFF legado; usar leitura binária correta (projeto atual já depende de `xlrd`) e não depender da instalação do Excel no Windows.


## Fase 6 — Recuperação do XML por chave (Meu Danfe API v2) — NOVO

**Fonte oficial consultada em 12/11/2026:** https://meudanfe.com.br/api e https://meudanfe.com.br/documentacao (iframe da documentação v2). A página oficial informa API-Key criada na Área do Cliente, e cobrança anunciada de **R$ 0,03 por busca de NF-e ainda não armazenada**; reconsultas de documentos previamente armazenados são anunciadas como gratuitas.

**Ponto de atenção:** o fornecedor confirma **busca de NF-e (modelo 55) por chave**, mas NÃO confirma busca de **NFC-e (modelo 65) por chave**. Converter um XML de NFC-e já possuído em PDF é funcionalidade distinta. Tratar recuperação por chave de NFC-e como **NÃO VALIDADA** até resposta da documentação/suporte e teste real. Não incluir NFC-e na fila de consultas pagas de NF-e sem contrato comprovado.

**Diferenciação:** chave de 44 dígitos não contém os dados completos da nota. O serviço deve recuperar XML existente a partir da chave, não sintetizar XML ou converter DANFE/PDF em documento fiscal válido.

### Novo fluxo
1. Coleta autorizada de planilhas SEFAZ-MT (`.xls`) para IE, competência, modalidade.
2. Extração de chaves, validação de 44 dígitos, DV, modelo 55/65, normalização, deduplicação e registro de origem/situação.
3. Verificar se XML completo já está armazenado localmente; se sim, não consultar terceiros.
4. Para chaves 55 sem XML local, registrar job pendente, estimativa de custo e aprovação do operador para consultas cobradas; consultar Meu Danfe via **endpoint/documentação confirmados** e API-Key guardada em variável de ambiente ou gerenciador de segredos.
5. Baixar XML da NF-e retornada, verificar estrutura, chave associada, modelo, protocolo, emitente, situação e presença de assinatura; validar criptograficamente a assinatura com ferramenta apropriada antes de considerá-lo íntegro/autêntico. `validar_xml.py` deste laboratório faz **somente validação estrutural**, não substitui validação de assinatura.
6. Armazenar sem sobrescrever, por IE/CNPJ autorizado, ano/mês, `nfe_emitidas`, `nfe_recebidas`; preservar o arquivo bruto e hash SHA-256, chave e origem.
7. Falhas ou documentos que não sejam `nfeProc`/`procNFe` completos (ex.: `resNFe`, HTML, PDF, dados reconstruídos) devem ser separados e não importados ao Domínio.
8. Para NFC-e 65, manter fila **AGUARDANDO_FONTE_XML**, sem fingir que o Meu Danfe as recupera pela chave. Investigar obtenção oficial/certificado A1/arquivo do emissor ou suporte Meu Danfe.
9. Gerar lote de XMLs válidos e relatório de reconciliação: chaves encontradas, XMLs obtidos, já existentes, não disponíveis, inválidos, cancelados/avisos e custos efetivamente cobrados. Preparar futura importação ao Domínio em fase posterior, sem enviar ainda.

### Estados por chave
`CHAVE_ENCONTRADA`, `JA_EXISTE_XML`, `AGUARDANDO_APROVACAO_CUSTO`, `CONSULTA_PENDENTE`, `CONSULTANDO`, `XML_BAIXADO`, `XML_VALIDADO_ESTRUTURALMENTE`, `XML_ASSINATURA_VERIFICADA`, `XML_INCOMPLETO`, `XML_INDISPONIVEL`, `FALHA_API`, `AGUARDANDO_FONTE_NFCE`, `PRONTO_PARA_IMPORTACAO`.

### Segurança e custos
- Requerer confirmação de credenciais, permissões, limites, quotas e **endpoint e formato real de resposta** da API v2. Não inventar endpoint, método HTTP ou cabeçalhos a partir de serviços diferentes.
- Não usar automação do site Meu Danfe enquanto existir API documentada, nem expor API-Key em logs.
- Aplicar orçamento máximo por execução, limite de concorrência conservador, controle de tentativas e backoff para 429/5xx, sem repetir automaticamente consultas pagas de resultado desconhecido.
- Informar cliente/escritório sobre processamento de dados fiscais por terceiro e verificar contrato, LGPD e retenção. O provedor afirma armazenar documentos consultados na Área do Cliente.
- Manter armazenamento seguro dos XMLs e logs auditáveis por chave, sem enviar notas reais em testes versionados.
- O exemplo anterior tem 71 chaves NF-e (6 emitidas + 65 recebidas), cujo custo **máximo ilustrativo a R$ 0,03 por chave ainda não armazenada** seria R$ 2,13. As 1.356 chaves NFC-e não entram nessa estimativa porque a recuperação por chave não está confirmada.

### Novos critérios de aceite
G. Recuperar via API, com uma chave NF-e real **autorizada**, ao menos um `nfeProc`/`procNFe` completo e conferir chave, protocolo, situação e campos essenciais contra a planilha.
H. Realizar validação criptográfica da assinatura antes de classificar como `PRONTO_PARA_IMPORTACAO`. Apenas XML bem-formado não basta.
I. Confirmar se a API realmente devolve XML fiscal completo ou XML reconstruído e se o XML pode ser importado ao Domínio; não prometer sucesso sem teste.
J. NFC-e por chave deve permanecer marcada como não suportada/não verificada até teste com fonte comprovada.
K. Produzir conciliação: total de chaves por modalidade = XMLs completos válidos + já existentes + indisponíveis + pendências/erros, com status e custo por consulta.
