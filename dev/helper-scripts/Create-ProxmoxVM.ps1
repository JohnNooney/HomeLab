param(
    [Parameter(Mandatory=$true)]
    [string]$VMName,
    
    [Parameter(Mandatory=$true)]
    [string]$IPAddress,
    
    [int]$MemoryGB = 12,
    [int]$ProcessorCount = 4,
    [int]$DiskSizeGB = 100
)

# Define VM paths
$vmPath = "E:\HyperV-VMs\VMs\$VMName"
$vhdPath = "E:\HyperV-VMs\VHDs\$VMName.vhdx"

# Create VM directory if it doesn't exist
New-Item -Path $vmPath -ItemType Directory -Force | Out-Null

# Create VM with custom path
New-VM -Name $VMName -MemoryStartupBytes ($MemoryGB * 1GB) -Generation 2 -SwitchName "ProxmoxCluster" -Path "E:\HyperV-VMs\VMs"

# Configure VM
Set-VM -Name $VMName -ProcessorCount $ProcessorCount -AutomaticCheckpointsEnabled $false
Set-VMMemory -VMName $VMName -DynamicMemoryEnabled $false

# Create and attach virtual hard disk
New-VHD -Path $vhdPath -SizeBytes ($DiskSizeGB * 1GB) -Dynamic
Add-VMHardDiskDrive -VMName $VMName -Path $vhdPath

# Attach Proxmox ISO
Add-VMDvdDrive -VMName $VMName -Path "E:\HyperV-VMs\ISOs\proxmox-ve_9.1-1.iso"

# Enable nested virtualization
Set-VMProcessor -VMName $VMName -ExposeVirtualizationExtensions $true

# Enable MAC spoofing
Get-VMNetworkAdapter -VMName $VMName | Set-VMNetworkAdapter -MacAddressSpoofing On

# Disable Secure Boot (Proxmox uses GRUB)
Set-VMFirmware -VMName $VMName -EnableSecureBoot Off

Write-Host "VM $VMName created successfully"
Write-Host "Assigned IP: $IPAddress"
Write-Host "Start the VM and complete Proxmox installation manually"