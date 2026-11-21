param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d{14}$')]
    [string]$Cnpj
)

# Somente leitura: localiza no repositorio pessoal do Windows (CurrentUser\My)
# o A1 valido, com chave privada, cujo CN termina em ":<CNPJ>" (padrao e-CNPJ)
# e devolve esse CN em Base64 (UTF-8). O Python grava o CN na preferencia
# auto_select_certificate do perfil Chrome desta execucao, para que o Chrome
# entregue o A1 ao portal sem abrir a janela nativa "Selecione um certificado".
# Nenhuma chave privada, senha ou arquivo PFX e lido ou exportado.
#
# Uso manual: powershell -ExecutionPolicy Bypass -File nome_certificado.ps1 -Cnpj 12345678000199

$ErrorActionPreference = 'Stop'
function Falhar([string]$mensagem) {
    # Mensagem direta no stderr: o Python a exibe ao operador.
    [Console]::Error.WriteLine("ERRO: $mensagem")
    exit 2
}
$tipoCn = [System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName
$agora = Get-Date
$todos = @(Get-ChildItem -Path Cert:\CurrentUser\My | Where-Object {
    $_.HasPrivateKey -and $_.GetNameInfo($tipoCn, $false) -like "*:$Cnpj"
})
$validos = @($todos | Where-Object { $_.NotBefore -le $agora -and $_.NotAfter -ge $agora })

if ($validos.Count -eq 0) {
    if ($todos.Count -gt 0) { Falhar 'A1 do CNPJ encontrado, mas fora da validade.' }
    Falhar 'Nenhum A1 com chave privada e CN terminado no CNPJ foi encontrado em CurrentUser\My.'
}
$nomes = @($validos | ForEach-Object { $_.GetNameInfo($tipoCn, $false) } | Sort-Object -Unique)
if ($nomes.Count -ne 1) { Falhar 'Mais de um nome de certificado valido para o CNPJ; selecao ambigua.' }
# O filtro do Chrome e pelo CN: com dois A1 de mesmo nome ele usa o primeiro.
if ($validos.Count -gt 1) { 'AVISO_MAIS_DE_UM_A1_VALIDO_MESMO_NOME' }
if ($todos.Count -gt $validos.Count) { 'AVISO_A1_VENCIDO_COM_MESMO_NOME_INSTALADO' }

'CN_BASE64:' + [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($nomes[0]))
exit 0
