param(
    [ValidatePattern('^(\d{14})?$')]
    [string]$Cnpj = ''
)

# Diagnostico do ambiente Windows para o login por A1 (nao altera nada).
# Uso: powershell -ExecutionPolicy Bypass -File diagnosticar_certificado.ps1 -Cnpj 12345678000199
# A saida mascara CNPJs; pode ser compartilhada para suporte.

function Mascarar([string]$texto) { return ($texto -replace '(\d{4})\d{6}(\d{4})', '$1******$2') }

$raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
'== PowerShell'
"Versao: $($PSVersionTable.PSVersion)"
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
"Terminal como administrador: $admin"
Get-ExecutionPolicy -List | Format-Table -AutoSize | Out-String

'== Arquivos .ps1 bloqueados pelo Windows (baixados da internet / zip)'
foreach ($arquivo in Get-ChildItem -Path $raiz -Filter *.ps1) {
    $zona = Get-Item -Path $arquivo.FullName -Stream Zone.Identifier -ErrorAction SilentlyContinue
    $estado = if ($zona) { 'BLOQUEADO (rode: Unblock-File)' } else { 'ok' }
    "$($arquivo.Name): $estado"
}

'== Politica do Chrome AutoSelectCertificateForUrls'
foreach ($chave in 'HKLM:\SOFTWARE\Policies\Google\Chrome\AutoSelectCertificateForUrls',
                   'HKCU:\Software\Policies\Google\Chrome\AutoSelectCertificateForUrls') {
    if (Test-Path $chave) {
        $props = Get-ItemProperty -Path $chave
        foreach ($nome in $props.PSObject.Properties.Name | Where-Object { $_ -match '^\d+$' }) {
            "$chave [$nome] = $(Mascarar ([string]$props.$nome))"
        }
    } else { "$chave : (nao existe)" }
}

'== Processos do Chrome em execucao'
$chromes = @(Get-Process -Name chrome -ErrorAction SilentlyContinue)
"Processos chrome.exe: $($chromes.Count)"

'== Certificados com chave privada em CurrentUser\My'
$tipoCn = [System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName
$agora = Get-Date
foreach ($c in Get-ChildItem -Path Cert:\CurrentUser\My | Where-Object { $_.HasPrivateKey }) {
    $cn = $c.GetNameInfo($tipoCn, $false)
    $valido = ($c.NotBefore -le $agora -and $c.NotAfter -ge $agora)
    $alvo = if ($Cnpj -and $cn -like "*:$Cnpj") { ' <== CNPJ informado' } else { '' }
    "$(Mascarar $cn) | valido ate $($c.NotAfter.ToString('yyyy-MM-dd')) | valido agora: $valido$alvo"
}
if ($Cnpj) {
    $n = @(Get-ChildItem -Path Cert:\CurrentUser\My | Where-Object {
        $_.HasPrivateKey -and $_.GetNameInfo($tipoCn, $false) -like "*:$Cnpj" -and
        $_.NotBefore -le $agora -and $_.NotAfter -ge $agora }).Count
    "Certificados validos para o CNPJ informado: $n (o esperado e 1)"
}
