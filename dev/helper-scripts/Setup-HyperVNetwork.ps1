# Setup-HyperVNetwork.ps1
# Configures Hyper-V networking for the HomeLab environment

param(
    [string]$SwitchName = "ProxmoxCluster",
    [string]$NATName = "ProxmoxClusterNAT",
    [string]$NATNetwork = "192.168.100.0/24",
    [string]$GatewayIP = "192.168.100.1"
)

Write-Host "Setting up Hyper-V network configuration..." -ForegroundColor Cyan

# Check if running as Administrator
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "This script must be run as Administrator"
    exit 1
}

# Check if switch already exists
$existingSwitch = Get-VMSwitch -Name $SwitchName -ErrorAction SilentlyContinue
if ($existingSwitch) {
    Write-Host "Virtual switch '$SwitchName' already exists" -ForegroundColor Yellow
} else {
    Write-Host "Creating virtual switch '$SwitchName'..." -ForegroundColor Green
    New-VMSwitch -Name $SwitchName -SwitchType Internal
}

# Configure IP address on the virtual switch interface
$interfaceAlias = "vEthernet ($SwitchName)"
$existingIP = Get-NetIPAddress -InterfaceAlias $interfaceAlias -IPAddress $GatewayIP -ErrorAction SilentlyContinue

if ($existingIP) {
    Write-Host "IP address $GatewayIP already configured on $interfaceAlias" -ForegroundColor Yellow
} else {
    Write-Host "Configuring IP address $GatewayIP on $interfaceAlias..." -ForegroundColor Green
    # Remove any existing IP configuration
    Get-NetIPAddress -InterfaceAlias $interfaceAlias -AddressFamily IPv4 -ErrorAction SilentlyContinue | Remove-NetIPAddress -Confirm:$false
    New-NetIPAddress -IPAddress $GatewayIP -PrefixLength 24 -InterfaceAlias $interfaceAlias
}

# Configure NAT
$existingNAT = Get-NetNat -Name $NATName -ErrorAction SilentlyContinue
if ($existingNAT) {
    Write-Host "NAT '$NATName' already exists" -ForegroundColor Yellow
} else {
    Write-Host "Creating NAT '$NATName' for network $NATNetwork..." -ForegroundColor Green
    New-NetNat -Name $NATName -InternalIPInterfaceAddressPrefix $NATNetwork
}

# Enable IP forwarding for WSL to Hyper-V communication
Write-Host "Enabling IP forwarding between WSL and Hyper-V..." -ForegroundColor Green
Set-NetIPInterface -InterfaceAlias "vEthernet (Default Switch)" -Forwarding Enabled -ErrorAction SilentlyContinue
Set-NetIPInterface -InterfaceAlias "vEthernet (WSL (Hyper-V firewall))" -Forwarding Enabled -ErrorAction SilentlyContinue

Write-Host "`nHyper-V network configuration complete!" -ForegroundColor Green
Write-Host "Switch Name: $SwitchName" -ForegroundColor Cyan
Write-Host "Gateway IP: $GatewayIP" -ForegroundColor Cyan
Write-Host "NAT Network: $NATNetwork" -ForegroundColor Cyan
