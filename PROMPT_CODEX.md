# Prompt para enviar ao Codex — SEFAZ-MT LAB v3 (XML completo)

Atue como engenheiro sênior de automações RPA em Python, usando DrissionPage no Windows. Trabalhe **exclusivamente neste projeto `sefaz-mt-lab`**, sem tocar na Central 68, sem copiar o Baixador Morpho e sem instalar soluções de bypass para Cloudflare/CAPTCHA.

**Leia integralmente `PRD_AUTOMACAO.md`, o `README.md` e o código atual antes de editar.** O resultado final deste projeto NÃO é a planilha, e sim XML completo pronto para futura importação contábil. O operador forneceu um vídeo demonstrando três consultas no portal da SEFAZ-MT, e três planilhas `.xls` como referência. Esses arquivos contêm dados fiscais reais: devem ficar em diretório local ignorado pelo Git (`referencias/`), com saída e screenshots também fora do controle de versão. Caso não estejam disponíveis no ambiente de trabalho do Codex, não invente seu conteúdo: use as especificações e testes sintéticos do PRD.

### Trabalho agora
1. Rode a suíte de testes atual (`python -m unittest discover -s tests -v`) e valide a correção do extrator para modelos 55 e 65, inclusive NFC-e com pontuação.
2. Analise os fluxos descritos no PRD. Mapeie a automação em três módulos independentes (`nfe_emitidas`, `nfe_recebidas`, `nfce_emitidas`) e compartilhe apenas componentes realmente comuns.
3. Use `agent-desktop` **se disponível e autorizado no ambiente** para inspecionar visualmente a página real no Chrome já autenticado pelo operador, identificar DOM e registrar seletores estáveis em `docs/mapeamento_dom.md`. Se a ferramenta não estiver disponível, produza uma etapa de inspeção assistida em DrissionPage, sem inventar seletores.
4. Implemente primeiro uma rotina end-to-end de **NF-e recebidas para uma única IE**, parametrizada por período, que navegue até a página correta, selecione Destinatário, consulte e exporte `.xls`, aguarde o download e extraia as chaves. Preserve os filtros UF e situação (padrão Todas).
5. Depois implemente NF-e emitidas trocando o rádio para Emissor. Em seguida NFC-e emitidas (campo Mês/Ano `MM/AAAA`, resultado possivelmente assíncrono). Não use o mesmo fluxo/formulário para NFC-e.
6. Registre evidências: etapa, IE parcialmente mascarada, tipo, período, sucesso/erro, arquivo exportado, quantidade de linhas, chaves válidas por modelo, canceladas, duração e screenshot anonimizado em falhas. Nunca registrar cookies, PFX, senha, CPF/CNPJ completo nos logs.
7. O robô não deve contornar verificações Cloudflare/CAPTCHA: se surgirem, pausar e pedir a intervenção humana/autorizada. Não declarar sucesso quando apenas a página abriu, o botão foi clicado ou existe um arquivo inválido.
8. Acrescente testes unitários com fixtures **sintéticas**, testes opcionais com amostras locais privadas e comando CLI documentado para cada rotina. Gere relatório de viabilidade por etapa (acesso, certificado, consulta, exportação, leitura e consolidação).

### Não negociável
- Não integrar com a Central 68.
- Apenas empresas com IE e acesso autorizado.
- Não presumir troca automática entre diferentes empresas: primeiro demonstrar sucesso com a IE que aparece autenticada.
- Extração em texto, DV válido, modelo 55/65, sem duplicar chaves; canceladas preservadas.
- Nunca inventar XPaths ou aceitar que uma automação funciona sem executar no portal e verificar o arquivo de saída.

Comece com `PRD_AUTOMACAO.md`, apresente um plano breve de execução e avance até conseguir implementar e testar offline tudo o que não depende de acesso ao portal. Para passos que exigem o Chrome autenticado, registre precisamente o que precisa inspecionar no ambiente local.


### Nova fase obrigatória: Meu Danfe API v2 → XML fiscal

1. Leia a documentação oficial `https://meudanfe.com.br/api` e `https://meudanfe.com.br/documentacao` (a página carrega a documentação v2 via iframe). Descubra **endpoints e contratos efetivamente documentados**, autenticadores, formato do retorno, tratamento de erros, cobrança/limites. Se não conseguir ler a documentação, produza uma lista objetiva dos trechos necessários e NÃO invente endpoints.
2. Crie um adaptador desacoplado `providers/meudanfe.py` com API-Key exclusivamente em segredos locais, timeouts, logs seguros, limite de consultas, orçamento por lote e retentativas idempotentes. Faça testes com `responses` sintéticas/mock. Não transcreva chave real nem API-Key para repositório.
3. Teste inicialmente **uma única NF-e modelo 55**, conferindo se o provedor devolve `nfeProc`/`procNFe` fiscal verdadeiro com assinatura e protocolo; XML reconstruído ou resumo não é equivalente. Valide também assinatura XMLDSig com ferramenta apropriada e compare `Id=NFe{chave}`, CNPJ e protocolo.
4. Separe NFC-e (modelo 65) em `AGUARDANDO_FONTE_NFCE`: o site confirma converter um XML já fornecido de NFC-e em PDF, mas **não comprova busca do XML de NFC-e só pela chave**. Consulte documentação/suporte antes de tentar.
5. Idempotência por chave + CNPJ/IE, histórico de tentativas, custo, origem (SEFAZ recebidas/emitidas/NFC-e), dados da nota, caminhos de XML, hash SHA-256 e conciliação dos totais. Nunca reconsultar chave já baixada/validada.
6. Salve arquivos originais por empresa/competência, recuse HTML/PDF/resNFe como XML completo e registre `XML_INCOMPLETO`, `XML_INDISPONIVEL`, `FALHA_API` sem mascarar como sucesso.
7. Prepare pasta `prontos_dominio/` com apenas XMLs completos, assinatura verificada e protocolo, além de manifesto de importação. **Não implemente integração ou envio ao Domínio ainda**; isso virá após teste de XML real no sistema.
8. Mantenha tudo isolado no projeto `sefaz-mt-lab`, sem integração com Central 68.

**Ordem obrigatória:** NF-e recebidas → chave → Meu Danfe → XML real validado → organização; depois NF-e emitidas; por último NFC-e, somente após comprovar fonte de XML.
