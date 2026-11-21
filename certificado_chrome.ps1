param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d{14}$')]
    [string]$Cnpj,
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 2147483647)]
    [int]$BrowserPid,
    [int]$TimeoutSegundos = 30
)

# Fallback: o caminho principal e a preferencia auto_select_certificate do
# perfil Chrome (nome_certificado.ps1 + sefaz_login.py), que impede a janela
# de aparecer.
# O seletor de certificados do Chrome e uma janela nativa, fora do DOM.
# Somente confirma um certificado cujo nome contenha o CNPJ esperado e que
# pertenca ao processo do Chrome aberto por esta execucao.
$ErrorActionPreference = 'Stop'
function Falhar([string]$mensagem) {
    # Mensagem direta no stderr: o Python a exibe ao operador.
    [Console]::Error.WriteLine("ERRO: $mensagem")
    exit 2
}
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes

$AE = [System.Windows.Automation.AutomationElement]
$CT = [System.Windows.Automation.ControlType]
$Escopo = [System.Windows.Automation.TreeScope]

function Mascarar([string]$texto) { return ($texto -replace '\d{6,}', '[num]') }

function Dialogos-Certificado {
    # Somente janelas de nivel superior do processo do navegador desta execucao.
    # O titulo da aba muda (AcessoWeb, Cloudflare, URL em carregamento), entao
    # o filtro e pelo PID e nao pelo titulo exato.
    $condPid = New-Object System.Windows.Automation.PropertyCondition($AE::ProcessIdProperty, $BrowserPid)
    $janelas = $AE::RootElement.FindAll($Escopo::Children, $condPid)
    $condJanela = New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, $CT::Window)
    $achados = @()
    foreach ($janela in $janelas) {
        $nome = [string]$janela.Current.Name
        if ($nome -like '*certificad*' -or $nome -like '*certificate*') { $achados += $janela; continue }
        # O dialogo modal da aba aparece como descendente da janela do Chrome.
        foreach ($d in $janela.FindAll($Escopo::Descendants, $condJanela)) {
            $n = [string]$d.Current.Name
            if ($n -like '*certificad*' -or $n -like '*certificate*') { $achados += $d }
        }
    }
    return ,$achados
}

$limite = (Get-Date).AddSeconds($TimeoutSegundos)
$janelaVista = $false
while ((Get-Date) -lt $limite) {
    $dialogos = Dialogos-Certificado
    if ($dialogos.Count -gt 1) { Falhar 'Mais de um dialogo de certificado encontrado.' }
    if ($dialogos.Count -eq 1) {
        $janelaVista = $true
        $itens = $dialogos[0].FindAll($Escopo::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
        $linhas = @($itens | Where-Object {
            ($_.Current.ControlType -eq $CT::DataItem -or $_.Current.ControlType -eq $CT::ListItem) -and
            ([string]$_.Current.Name) -like "*:$Cnpj*"
        })
        # Linha e celula podem ter o mesmo texto; so a linha e selecionavel.
        $selecionaveis = @($linhas | Where-Object {
            $p = $null
            $_.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$p)
        })
        if ($selecionaveis.Count -ne 1) {
            $vistos = @($itens | Where-Object {
                $_.Current.ControlType -eq $CT::DataItem -or $_.Current.ControlType -eq $CT::ListItem
            } | ForEach-Object { Mascarar ([string]$_.Current.Name) })
            [Console]::Error.WriteLine("Itens do dialogo: " + ($vistos -join ' | '))
            Falhar "Certificado correspondente ao CNPJ nao encontrado de forma unica ($($selecionaveis.Count) selecionaveis, $($linhas.Count) com o CNPJ)."
        }
        $selecao = $selecionaveis[0].GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern)
        if (-not $selecao.Current.IsSelected) { $selecao.Select() }
        Start-Sleep -Milliseconds 300
        $botoes = @($itens | Where-Object {
            $_.Current.ControlType -eq $CT::Button -and ([string]$_.Current.Name).Trim() -in @('OK', 'Ok')
        })
        if ($botoes.Count -ne 1) { Falhar 'Botao OK do dialogo nao encontrado de forma unica.' }
        $botoes[0].GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
        'CERTIFICADO_CONFIRMADO'
        exit 0
    }
    Start-Sleep -Milliseconds 500
}
if ($janelaVista) { Falhar 'Dialogo de certificado sumiu antes da confirmacao.' }
Falhar 'Tempo esgotado aguardando o seletor de certificado do Chrome (nenhum dialogo do PID informado).'
