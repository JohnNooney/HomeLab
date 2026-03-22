# Configure-ProxmoxVMSettings.ps1
# Configures nested virtualization and MAC spoofing for Proxmox VMs

param(
    [Parameter(Mandatory=$true)]
    [string[]]$VMNames
)

Write-Host "Configuring Hyper-V settings for Proxmox VMs..." -ForegroundColor Cyan

# Check if running as Administrator
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "This script must be run as Administrator"
    exit 1
}

foreach ($VMName in $VMNames) {
    Write-Host "`nConfiguring VM: $VMName" -ForegroundColor Green
    
    # Check if VM exists
    $vm = Get-VM -Name $VMName -ErrorAction SilentlyContinue
    if (-not $vm) {
        Write-Warning "VM '$VMName' not found, skipping..."
        continue
    }
    
    # Enable nested virtualization
    Write-Host "  - Enabling nested virtualization..." -ForegroundColor Yellow
    Set-VMProcessor -VMName $VMName -ExposeVirtualizationExtensions $true
    
    # Enable MAC address spoofing
    Write-Host "  - Enabling MAC address spoofing..." -ForegroundColor Yellow
    Get-VMNetworkAdapter -VMName $VMName | Set-VMNetworkAdapter -MacAddressSpoofing On
    
    Write-Host "  - Configuration complete for $VMName" -ForegroundColor Green
}

Write-Host "`nAll VMs configured successfully!" -ForegroundColor Green
