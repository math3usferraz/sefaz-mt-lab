param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d{14}$')]
    [string]$Cnpj,
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 2147483647)]
    [int]$BrowserPid,
    [int]$TimeoutSegundos = 30
)

# O seletor de certificados do Chrome e uma janela nativa, fora do DOM.
# Somente confirma um certificado cujo nome contenha o CNPJ esperado.
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes

$limite = (Get-Date).AddSeconds($TimeoutSegundos)
while ((Get-Date) -lt $limite) {
    $janelas = [System.Windows.Automation.AutomationElement]::RootElement.FindAll(
        [System.Windows.Automation.TreeScope]::Children,
        [System.Windows.Automation.Condition]::TrueCondition
    )
    $candidatas = @($janelas | Where-Object {
        $_.Current.Name -eq 'AcessoWeb - Google Chrome' -and
        $_.Current.ProcessId -eq $BrowserPid
    })
    if ($candidatas.Count -gt 1) { throw 'Mais de uma janela AcessoWeb encontrada.' }
    if ($candidatas.Count -eq 1) {
        $elementos = $candidatas[0].FindAll(
            [System.Windows.Automation.TreeScope]::Descendants,
            [System.Windows.Automation.Condition]::TrueCondition
        )
        $dialogos = @($elementos | Where-Object {
            $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Window -and
            $_.Current.Name -like '*certificado*'
        })
        if ($dialogos.Count -gt 1) { throw 'Mais de um dialogo de certificado encontrado.' }
        if ($dialogos.Count -eq 1) {
            $itens = $dialogos[0].FindAll(
                [System.Windows.Automation.TreeScope]::Descendants,
                [System.Windows.Automation.Condition]::TrueCondition
            )
            $certificados = @($itens | Where-Object {
                $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::DataItem -and
                $_.Current.Name.EndsWith(":$Cnpj")
            })
            if ($certificados.Count -ne 1) { throw 'Certificado correspondente ao CNPJ nao encontrado de forma unica.' }
            $selecao = $certificados[0].GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern)
            if (-not $selecao.Current.IsSelected) { $selecao.Select() }
            $botoes = @($itens | Where-Object {
                $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button -and
                $_.Current.Name -eq 'OK'
            })
            if ($botoes.Count -ne 1) { throw 'Botao OK do dialogo nao encontrado de forma unica.' }
            $botoes[0].GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
            'CERTIFICADO_CONFIRMADO'
            exit 0
        }
    }
    Start-Sleep -Milliseconds 500
}
throw 'Tempo esgotado aguardando o seletor de certificado do Chrome.'
