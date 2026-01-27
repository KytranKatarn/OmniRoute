#!/usr/bin/env python3
"""
A.R.C.H.I.E. Host System Monitor
Runs on the HOST machine to collect system data inaccessible from Docker containers.
Writes data to a JSON file that the container can read.

Usage:
    python3 host_monitor.py              # Run once
    python3 host_monitor.py --daemon     # Run continuously (every 30 seconds)
    python3 host_monitor.py --interval 10  # Custom interval in seconds

Output:
    /mnt/archie_brain/host_monitor_data.json
"""

import json
import os
import subprocess
import time
import argparse
from datetime import datetime
from pathlib import Path

OUTPUT_FILE = '/mnt/archie_brain/host_monitor_data.json'
BANDWIDTH_FILE = os.path.join(os.path.dirname(OUTPUT_FILE), 'bandwidth_history.json')


def run_command(cmd, timeout=10):
    """Run a shell command and return output"""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=isinstance(cmd, str)
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except Exception as e:
        return None


def get_lvm_info():
    """Get LVM volume group and logical volume information"""
    info = {'vgs': [], 'lvs': [], 'pvs': []}

    # Get Physical Volumes
    output = run_command(['pvs', '--noheadings', '--units', 'g', '-o', 'pv_name,vg_name,pv_size,pv_free'])
    if output:
        for line in output.split('\n'):
            parts = line.split()
            if len(parts) >= 4:
                info['pvs'].append({
                    'pv_name': parts[0],
                    'vg_name': parts[1],
                    'pv_size': parts[2],
                    'pv_free': parts[3]
                })

    # Get Volume Groups
    output = run_command(['vgs', '--noheadings', '--units', 'g', '-o', 'vg_name,vg_size,vg_free'])
    if output:
        for line in output.split('\n'):
            parts = line.split()
            if len(parts) >= 3:
                vg_size = float(parts[1].rstrip('gG')) if parts[1] else 0
                vg_free = float(parts[2].rstrip('gG')) if parts[2] else 0
                info['vgs'].append({
                    'vg_name': parts[0],
                    'vg_size_gb': round(vg_size, 2),
                    'vg_free_gb': round(vg_free, 2)
                })

    # Get Logical Volumes
    output = run_command(['lvs', '--noheadings', '--units', 'g', '-o', 'lv_name,vg_name,lv_size'])
    if output:
        for line in output.split('\n'):
            parts = line.split()
            if len(parts) >= 3:
                lv_size = float(parts[2].rstrip('gG')) if parts[2] else 0
                info['lvs'].append({
                    'lv_name': parts[0],
                    'vg_name': parts[1],
                    'lv_size_gb': round(lv_size, 2)
                })

    return info if (info['vgs'] or info['lvs'] or info['pvs']) else None


def get_raid_status():
    """Check for RAID arrays"""
    if not os.path.exists('/proc/mdstat'):
        return None

    try:
        with open('/proc/mdstat', 'r') as f:
            content = f.read()

        if 'md' not in content:
            return None

        arrays = []
        lines = content.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith('md'):
                parts = line.split()
                if len(parts) >= 4:
                    name = parts[0].rstrip(':')
                    status = 'active' if 'active' in line else 'inactive'
                    level = ''
                    devices = []

                    # Find RAID level
                    for p in parts:
                        if p.startswith('raid'):
                            level = p
                            break

                    # Find devices
                    for p in parts[3:]:
                        if '[' in p:
                            devices.append(p)

                    # Check next line for status
                    health = 'healthy'
                    if i + 1 < len(lines):
                        next_line = lines[i + 1]
                        if '_' in next_line:
                            health = 'degraded'

                    arrays.append({
                        'name': name,
                        'status': status,
                        'level': level,
                        'devices': devices,
                        'health': health
                    })
            i += 1

        return {'arrays': arrays, 'healthy': all(a['health'] == 'healthy' for a in arrays)} if arrays else None
    except:
        return None


def get_systemd_services():
    """Get systemd services (important ones)"""
    services = []

    # List of important services to monitor
    important_services = [
        'docker', 'nginx', 'postgresql', 'ssh', 'sshd',
        'cron', 'systemd-resolved', 'networkd-dispatcher',
        'ufw', 'fail2ban', 'ollama'
    ]

    output = run_command(['systemctl', 'list-units', '--type=service', '--all', '--no-pager', '--plain'])
    if output:
        for line in output.split('\n')[1:]:  # Skip header
            if '.service' not in line:
                continue

            parts = line.split()
            if len(parts) >= 4:
                name = parts[0].replace('.service', '')
                status = parts[2]  # active/inactive
                sub_status = parts[3]

                # Only include important services or active ones
                if name in important_services or status == 'active':
                    # Check if enabled
                    enabled_output = run_command(['systemctl', 'is-enabled', f'{name}.service'])
                    enabled = enabled_output == 'enabled' if enabled_output else False

                    services.append({
                        'name': name,
                        'status': status,
                        'sub_status': sub_status,
                        'enabled': enabled
                    })

    return services


def get_network_info():
    """Get host network information including interfaces, listening ports, and connections"""
    info = {
        'hostname': '',
        'interfaces': [],
        'primary_ip': None,
        'listening_ports': [],
        'connections': [],
        'dns_servers': [],
        'gateway': None
    }

    # Hostname
    info['hostname'] = run_command(['hostname']) or 'unknown'

    # Get interfaces with IPs
    output = run_command(['ip', '-4', 'addr', 'show'])
    if output:
        current_iface = None
        for line in output.split('\n'):
            if not line.startswith(' '):
                parts = line.split(':')
                if len(parts) >= 2:
                    current_iface = parts[1].strip().split('@')[0]
            elif 'inet ' in line and current_iface:
                parts = line.strip().split()
                if len(parts) >= 2:
                    ip_with_mask = parts[1]
                    ip = ip_with_mask.split('/')[0]
                    if not ip.startswith('127.'):
                        info['interfaces'].append({
                            'name': current_iface,
                            'ip': ip,
                            'cidr': ip_with_mask
                        })
                        if not info['primary_ip']:
                            info['primary_ip'] = ip

    # Default gateway
    gw_output = run_command(['ip', 'route', 'show', 'default'])
    if gw_output:
        parts = gw_output.split()
        if 'via' in parts:
            idx = parts.index('via')
            if idx + 1 < len(parts):
                info['gateway'] = parts[idx + 1]

    # DNS servers from /etc/resolv.conf
    try:
        with open('/etc/resolv.conf', 'r') as f:
            for line in f:
                if line.startswith('nameserver'):
                    dns = line.split()[1]
                    if dns not in info['dns_servers']:
                        info['dns_servers'].append(dns)
    except OSError:
        pass

    # Listening ports via ss
    ss_output = run_command(['ss', '-tlnp'])
    if ss_output:
        for line in ss_output.split('\n')[1:]:  # Skip header
            parts = line.split()
            if len(parts) < 5:
                continue
            try:
                local_addr = parts[3]
                # Parse address:port (handles both IPv4 and [::]:port)
                if ']:' in local_addr:
                    ip, port = local_addr.rsplit(':', 1)
                    ip = ip.strip('[]')
                elif local_addr.startswith('*:'):
                    ip, port = '0.0.0.0', local_addr[2:]
                else:
                    ip, port = local_addr.rsplit(':', 1)
                port = int(port)

                # Extract process name from "users:(("name",pid=X,...))"
                process = None
                pid = None
                if len(parts) >= 6 and 'users:' in parts[5]:
                    proc_str = parts[5]
                    if '(("' in proc_str:
                        process = proc_str.split('(("')[1].split('"')[0]
                    if 'pid=' in proc_str:
                        pid = int(proc_str.split('pid=')[1].split(',')[0])

                info['listening_ports'].append({
                    'port': port,
                    'ip': ip,
                    'protocol': 'tcp',
                    'process': process,
                    'pid': pid
                })
            except (ValueError, IndexError):
                continue

        info['listening_ports'].sort(key=lambda x: x['port'])

    # Active connections via ss (established, limit to 50)
    # ss -tnp state established output: Recv-Q Send-Q Local Peer [Process]
    # Note: no State column in this mode
    conn_output = run_command(['ss', '-tnp', 'state', 'established'])
    if conn_output:
        for line in conn_output.split('\n')[1:]:  # Skip header
            parts = line.split()
            if len(parts) < 4:
                continue
            try:
                local_addr = parts[2]
                remote_addr = parts[3]

                process = None
                pid = None
                if len(parts) >= 5 and 'users:' in parts[4]:
                    proc_str = parts[4]
                    if '(("' in proc_str:
                        process = proc_str.split('(("')[1].split('"')[0]
                    if 'pid=' in proc_str:
                        pid = int(proc_str.split('pid=')[1].split(',')[0])

                info['connections'].append({
                    'local_addr': local_addr,
                    'remote_addr': remote_addr,
                    'status': 'ESTABLISHED',
                    'process': process,
                    'pid': pid
                })
            except (ValueError, IndexError):
                continue

        info['connections'] = info['connections'][:50]

    # Per-interface bandwidth from /proc/net/dev
    bandwidth_interfaces = []
    try:
        with open('/proc/net/dev', 'r') as f:
            for line in f:
                line = line.strip()
                if ':' not in line or line.startswith('Inter') or line.startswith(' face'):
                    continue
                parts = line.split(':')
                iface_name = parts[0].strip()
                values = parts[1].split()
                if len(values) >= 10:
                    bandwidth_interfaces.append({
                        'name': iface_name,
                        'rx_bytes': int(values[0]),
                        'rx_packets': int(values[1]),
                        'tx_bytes': int(values[8]),
                        'tx_packets': int(values[9])
                    })
    except OSError:
        pass
    info['bandwidth_interfaces'] = bandwidth_interfaces

    return info


def get_disk_layout():
    """Get host disk and partition layout"""
    disks = []

    # Use lsblk to get disk info
    output = run_command(['lsblk', '-J', '-b', '-o', 'NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,PKNAME,MODEL'])
    if output:
        try:
            data = json.loads(output)

            for device in data.get('blockdevices', []):
                if device.get('type') == 'disk':
                    disk_info = {
                        'name': device.get('name'),
                        'device': f"/dev/{device.get('name')}",
                        'size_bytes': int(device.get('size', 0)),
                        'size_gb': round(int(device.get('size', 0)) / (1024**3), 2),
                        'model': device.get('model', 'Unknown').strip() if device.get('model') else 'Unknown',
                        'partitions': []
                    }

                    # Get partitions
                    for child in device.get('children', []):
                        part_info = {
                            'name': child.get('name'),
                            'device': f"/dev/{child.get('name')}",
                            'size_bytes': int(child.get('size', 0)),
                            'size_gb': round(int(child.get('size', 0)) / (1024**3), 2),
                            'type': child.get('type'),
                            'fstype': child.get('fstype') or 'Unknown',
                            'mountpoint': child.get('mountpoint'),
                            'children': []
                        }

                        # Check for LVM or other children
                        for grandchild in child.get('children', []):
                            part_info['children'].append({
                                'name': grandchild.get('name'),
                                'device': f"/dev/mapper/{grandchild.get('name')}" if grandchild.get('type') == 'lvm' else f"/dev/{grandchild.get('name')}",
                                'size_gb': round(int(grandchild.get('size', 0)) / (1024**3), 2),
                                'type': grandchild.get('type'),
                                'fstype': grandchild.get('fstype'),
                                'mountpoint': grandchild.get('mountpoint')
                            })

                        disk_info['partitions'].append(part_info)

                    disks.append(disk_info)
        except Exception:
            pass

    # Check for unallocated space using fdisk
    for disk in disks:
        disk['unallocated_gb'] = 0
        fdisk_output = run_command(['fdisk', '-l', disk['device']])
        if fdisk_output:
            # Calculate total partition sizes
            total_partitioned = sum(p['size_bytes'] for p in disk['partitions'])
            if disk['size_bytes'] > total_partitioned:
                disk['unallocated_gb'] = round((disk['size_bytes'] - total_partitioned) / (1024**3), 2)

    # Add disk usage stats for mounted partitions
    for disk in disks:
        for part in disk['partitions']:
            _add_usage_stats(part)
            for child in part.get('children', []):
                _add_usage_stats(child)

    # Enrich with blkid data (UUID, LABEL)
    blkid = get_blkid_info()
    for disk in disks:
        for part in disk['partitions']:
            dev = part.get('device', '')
            if dev in blkid:
                part['uuid'] = blkid[dev].get('uuid')
                part['label'] = blkid[dev].get('label')
            for child in part.get('children', []):
                cdev = child.get('device', '')
                if cdev in blkid:
                    child['uuid'] = blkid[cdev].get('uuid')
                    child['label'] = blkid[cdev].get('label')

    # Enrich with SMART health
    smart = get_smart_health()
    for disk in disks:
        disk['smart_health'] = smart.get(disk['name'], 'unavailable')

    # Enrich with I/O stats
    io_stats = get_disk_io_rates()
    for disk in disks:
        if disk['name'] in io_stats:
            disk['io'] = io_stats[disk['name']]

    return disks


def _add_usage_stats(partition):
    """Add usage stats (used/free/percent) to a mounted partition"""
    mp = partition.get('mountpoint')
    if not mp:
        return
    try:
        st = os.statvfs(mp)
        total = st.f_frsize * st.f_blocks
        free = st.f_frsize * st.f_bavail
        used = total - free
        partition['usage'] = {
            'total_gb': round(total / (1024**3), 2),
            'used_gb': round(used / (1024**3), 2),
            'free_gb': round(free / (1024**3), 2),
            'percent': round((used / total) * 100, 1) if total > 0 else 0
        }
    except OSError:
        pass


def get_blkid_info():
    """Get partition UUID and LABEL from blkid"""
    info = {}
    output = run_command(['blkid'])
    if output:
        for line in output.split('\n'):
            if ':' not in line:
                continue
            device = line.split(':')[0].strip()
            entry = {}
            if 'UUID="' in line:
                entry['uuid'] = line.split('UUID="')[1].split('"')[0]
            if 'LABEL="' in line:
                entry['label'] = line.split('LABEL="')[1].split('"')[0]
            if 'TYPE="' in line:
                entry['type'] = line.split('TYPE="')[1].split('"')[0]
            if 'PARTUUID="' in line:
                entry['partuuid'] = line.split('PARTUUID="')[1].split('"')[0]
            if entry:
                info[device] = entry
    return info


def get_disk_io_rates():
    """Get disk I/O stats from /proc/diskstats"""
    stats = {}
    try:
        with open('/proc/diskstats', 'r') as f:
            for line in f:
                parts = line.split()
                if len(parts) < 14:
                    continue
                name = parts[2]
                stats[name] = {
                    'reads_completed': int(parts[3]),
                    'sectors_read': int(parts[5]),
                    'writes_completed': int(parts[7]),
                    'sectors_written': int(parts[9]),
                    'io_in_progress': int(parts[11]),
                }
    except OSError:
        pass
    return stats


def get_smart_health():
    """Get basic SMART health for each disk"""
    health = {}
    output = run_command(['lsblk', '-dn', '-o', 'NAME,TYPE'])
    if not output:
        return health
    for line in output.split('\n'):
        parts = line.split()
        if len(parts) >= 2 and parts[1] == 'disk':
            name = parts[0]
            smart_out = run_command(['smartctl', '-H', f'/dev/{name}'], timeout=5)
            if smart_out:
                if 'PASSED' in smart_out:
                    health[name] = 'healthy'
                elif 'FAILED' in smart_out:
                    health[name] = 'failing'
                else:
                    health[name] = 'unknown'
            else:
                health[name] = 'unavailable'
    return health


def get_gpu_info():
    """Get GPU information from the host"""
    gpus = []

    # Detect GPUs via lspci
    output = run_command('lspci 2>/dev/null | grep -i -E "VGA|3D|Display"')
    if not output:
        return None

    for line in output.split('\n'):
        line = line.strip()
        if not line:
            continue

        # Parse lspci output: "05:00.0 VGA compatible controller: NVIDIA Corporation GM204GL [Quadro M4000] (rev a1)"
        pci_addr = line.split()[0] if line.split() else ''
        vendor = 'unknown'
        model = line

        # Extract vendor and model
        if 'NVIDIA' in line.upper():
            vendor = 'nvidia'
            # Extract bracketed model name if present: [Quadro M4000]
            if '[' in line and ']' in line:
                model = line[line.index('[') + 1:line.index(']')]
            else:
                # Fall back to text after the colon
                model = line.split(':', 1)[-1].strip() if ':' in line else line
        elif 'AMD' in line.upper() or 'ATI' in line.upper():
            vendor = 'amd'
            if '[' in line and ']' in line:
                model = line[line.index('[') + 1:line.index(']')]
            else:
                model = line.split(':', 1)[-1].strip() if ':' in line else line
        elif 'INTEL' in line.upper():
            vendor = 'intel'
            if '[' in line and ']' in line:
                model = line[line.index('[') + 1:line.index(']')]
            else:
                model = line.split(':', 1)[-1].strip() if ':' in line else line

        gpu = {
            'pci_address': pci_addr,
            'vendor': vendor,
            'model': model,
            'temperature': None,
            'vram_total_mb': None,
            'vram_used_mb': None,
            'utilization_percent': None,
            'driver': None
        }

        # Try nvidia-smi for NVIDIA GPUs
        if vendor == 'nvidia':
            smi_output = run_command(
                'nvidia-smi --query-gpu=memory.total,memory.used,utilization.gpu,temperature.gpu,driver_version '
                '--format=csv,noheader,nounits 2>/dev/null'
            )
            if smi_output:
                parts = [p.strip() for p in smi_output.split(',')]
                if len(parts) >= 5:
                    gpu['vram_total_mb'] = int(parts[0]) if parts[0].isdigit() else None
                    gpu['vram_used_mb'] = int(parts[1]) if parts[1].isdigit() else None
                    gpu['utilization_percent'] = int(parts[2]) if parts[2].isdigit() else None
                    gpu['temperature'] = int(parts[3]) if parts[3].isdigit() else None
                    gpu['driver'] = parts[4] if parts[4] != '[N/A]' else None

        # Fall back to hwmon for temperature (nouveau driver, etc.)
        if gpu['temperature'] is None:
            gpu['temperature'] = _read_hwmon_gpu_temp()

        # Detect driver in use
        if gpu['driver'] is None:
            drv_output = run_command(f'lspci -k -s {pci_addr} 2>/dev/null')
            if drv_output:
                for drv_line in drv_output.split('\n'):
                    if 'Kernel driver in use:' in drv_line:
                        gpu['driver'] = drv_line.split(':')[-1].strip()
                        break

        gpus.append(gpu)

    return gpus if gpus else None


def _read_hwmon_gpu_temp():
    """Read GPU temperature from hwmon (nouveau, amdgpu, etc.)"""
    hwmon_base = '/sys/class/hwmon'
    gpu_drivers = {'nouveau', 'amdgpu', 'radeon', 'nvidia'}
    try:
        for entry in os.listdir(hwmon_base):
            name_path = os.path.join(hwmon_base, entry, 'name')
            try:
                with open(name_path, 'r') as f:
                    name = f.read().strip()
                if name in gpu_drivers:
                    temp_path = os.path.join(hwmon_base, entry, 'temp1_input')
                    with open(temp_path, 'r') as f:
                        return int(f.read().strip()) // 1000
            except (OSError, ValueError):
                continue
    except OSError:
        pass
    return None


def get_cpu_info():
    """Get CPU information from the host"""
    info = {
        'model': None,
        'physical_cores': None,
        'logical_cores': None,
        'temperature': None,
        'temperatures': []
    }

    # CPU model from /proc/cpuinfo
    try:
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                if line.startswith('model name'):
                    info['model'] = line.split(':', 1)[1].strip()
                    break
    except OSError:
        pass

    # Core counts
    try:
        info['logical_cores'] = os.cpu_count()
    except Exception:
        pass

    # Physical cores (count unique core IDs)
    try:
        with open('/proc/cpuinfo', 'r') as f:
            core_ids = set()
            for line in f:
                if line.startswith('core id'):
                    core_ids.add(line.split(':', 1)[1].strip())
            if core_ids:
                info['physical_cores'] = len(core_ids)
    except OSError:
        pass

    # CPU temperatures from coretemp hwmon
    hwmon_base = '/sys/class/hwmon'
    try:
        for entry in os.listdir(hwmon_base):
            name_path = os.path.join(hwmon_base, entry, 'name')
            try:
                with open(name_path, 'r') as f:
                    name = f.read().strip()
                if name in ('coretemp', 'k10temp', 'zenpower'):
                    hwmon_dir = os.path.join(hwmon_base, entry)
                    temps = []
                    for fname in sorted(os.listdir(hwmon_dir)):
                        if fname.startswith('temp') and fname.endswith('_input'):
                            try:
                                with open(os.path.join(hwmon_dir, fname), 'r') as f:
                                    temp_c = int(f.read().strip()) // 1000
                                    temps.append(temp_c)
                            except (OSError, ValueError):
                                continue
                    if temps:
                        info['temperatures'] = temps
                        info['temperature'] = max(temps)
                    break
            except (OSError, ValueError):
                continue
    except OSError:
        pass

    return info


def get_system_info():
    """Get host system information"""
    info = {
        'hostname': None,
        'distribution': None,
        'version_id': None,
        'kernel': None,
        'uptime_seconds': None,
        'uptime_formatted': None,
        'boot_time': None,
        'load_average': None,
        'process_count': None,
        'users_logged_in': None,
        'architecture': None
    }

    # Hostname
    info['hostname'] = run_command(['hostname']) or os.uname().nodename

    # Distribution from /etc/os-release
    try:
        with open('/etc/os-release', 'r') as f:
            for line in f:
                if line.startswith('PRETTY_NAME='):
                    info['distribution'] = line.split('=', 1)[1].strip().strip('"')
                elif line.startswith('VERSION_ID='):
                    info['version_id'] = line.split('=', 1)[1].strip().strip('"')
    except OSError:
        pass

    # Kernel
    info['kernel'] = os.uname().release

    # Architecture
    info['architecture'] = os.uname().machine

    # Uptime from /proc/uptime
    try:
        with open('/proc/uptime', 'r') as f:
            uptime_secs = float(f.read().split()[0])
            info['uptime_seconds'] = int(uptime_secs)
            days = int(uptime_secs) // 86400
            hours = (int(uptime_secs) % 86400) // 3600
            minutes = (int(uptime_secs) % 3600) // 60
            parts = []
            if days > 0:
                parts.append(f"{days}d")
            parts.append(f"{hours}h")
            parts.append(f"{minutes}m")
            info['uptime_formatted'] = ' '.join(parts)
    except (OSError, ValueError):
        pass

    # Boot time
    boot_output = run_command(['who', '-b'])
    if boot_output:
        # Format: "system boot  2026-01-25 13:16"
        parts = boot_output.strip().split()
        if len(parts) >= 4:
            info['boot_time'] = f"{parts[-2]} {parts[-1]}"

    # Load average
    try:
        load = os.getloadavg()
        info['load_average'] = [round(l, 2) for l in load]
    except OSError:
        pass

    # Process count
    try:
        count = sum(1 for entry in os.listdir('/proc') if entry.isdigit())
        info['process_count'] = count
    except OSError:
        pass

    # Users logged in
    who_output = run_command(['who'])
    if who_output:
        info['users_logged_in'] = len([l for l in who_output.split('\n') if l.strip()])
    else:
        info['users_logged_in'] = 0

    return info


def get_process_list(limit=100):
    """Get running processes from the host via ps aux"""
    processes = []

    output = run_command(['ps', 'aux', '--sort=-pcpu'], timeout=15)
    if not output:
        return processes

    # ps aux status codes to readable names
    status_map = {
        'R': 'running', 'S': 'sleeping', 'D': 'disk-sleep',
        'T': 'stopped', 'Z': 'zombie', 'I': 'idle',
        'X': 'dead', 'W': 'paging'
    }

    lines = output.split('\n')
    for line in lines[1:]:  # Skip header
        parts = line.split(None, 10)
        if len(parts) < 11:
            continue
        try:
            raw_stat = parts[7]
            status = status_map.get(raw_stat[0], raw_stat) if raw_stat else 'unknown'
            # Extract just the command name (not full path with args)
            command = parts[10]
            name = command.split()[0].rsplit('/', 1)[-1] if command else 'unknown'

            processes.append({
                'pid': int(parts[1]),
                'name': name[:80],
                'command': command[:200],
                'user': parts[0],
                'cpu_percent': float(parts[2]),
                'memory_percent': float(parts[3]),
                'rss_kb': int(parts[5]),
                'status': status,
            })
        except (ValueError, IndexError):
            continue

    return processes[:limit]


def update_bandwidth_history(network_data, container_bandwidth=None):
    """Update rolling bandwidth history buffer from current network data"""
    try:
        # Load existing history
        history = {"samples": [], "max_samples": 60}
        if os.path.exists(BANDWIDTH_FILE):
            try:
                with open(BANDWIDTH_FILE, 'r') as f:
                    history = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        now = time.time()
        bandwidth_interfaces = network_data.get('bandwidth_interfaces', [])

        # Build current counters
        current = {}
        for iface in bandwidth_interfaces:
            current[iface['name']] = {
                'rx_bytes': iface['rx_bytes'],
                'tx_bytes': iface['tx_bytes'],
                'rx_packets': iface['rx_packets'],
                'tx_packets': iface['tx_packets']
            }

        # Calculate rates from previous sample
        rates = {}
        if history['samples']:
            prev = history['samples'][-1]
            dt = now - prev.get('timestamp', now)
            if dt > 0:
                prev_counters = prev.get('counters', {})
                for name, cur_vals in current.items():
                    if name in prev_counters:
                        prev_vals = prev_counters[name]
                        rx_delta = max(0, cur_vals['rx_bytes'] - prev_vals.get('rx_bytes', 0))
                        tx_delta = max(0, cur_vals['tx_bytes'] - prev_vals.get('tx_bytes', 0))
                        rates[name] = {
                            'rx_bps': round(rx_delta / dt),
                            'tx_bps': round(tx_delta / dt)
                        }

        # Build sample
        sample = {
            'timestamp': now,
            'counters': current,
            'rates': rates
        }

        # Add container bandwidth if available
        if container_bandwidth:
            sample['containers'] = [
                {'name': c['name'], 'rx_bytes': c['rx_bytes'], 'tx_bytes': c['tx_bytes']}
                for c in container_bandwidth
            ]

        history['samples'].append(sample)

        # Trim to max samples
        max_s = history.get('max_samples', 60)
        if len(history['samples']) > max_s:
            history['samples'] = history['samples'][-max_s:]

        # Write back
        with open(BANDWIDTH_FILE, 'w') as f:
            json.dump(history, f, indent=2)
        os.chmod(BANDWIDTH_FILE, 0o644)

    except Exception as e:
        print(f"Error updating bandwidth history: {e}")


def get_container_bandwidth():
    """Get per-container network I/O from docker stats"""
    containers = []
    output = run_command(['docker', 'stats', '--no-stream', '--format', '{{.Name}}\t{{.NetIO}}'], timeout=15)
    if not output:
        return containers
    for line in output.strip().split('\n'):
        if '\t' not in line:
            continue
        parts = line.split('\t', 1)
        if len(parts) < 2:
            continue
        name = parts[0].strip()
        net_io = parts[1].strip()
        # Parse "1.23MB / 4.56GB" format
        rx_str, tx_str = '0B', '0B'
        if '/' in net_io:
            io_parts = net_io.split('/')
            rx_str = io_parts[0].strip()
            tx_str = io_parts[1].strip()

        def parse_size(s):
            s = s.strip().upper()
            multipliers = {'B': 1, 'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4,
                           'KIB': 1024, 'MIB': 1024**2, 'GIB': 1024**3, 'TIB': 1024**4}
            for suffix, mult in sorted(multipliers.items(), key=lambda x: -len(x[0])):
                if s.endswith(suffix):
                    try:
                        return int(float(s[:-len(suffix)].strip()) * mult)
                    except ValueError:
                        return 0
            try:
                return int(float(s))
            except ValueError:
                return 0

        containers.append({
            'name': name,
            'rx_bytes': parse_size(rx_str),
            'tx_bytes': parse_size(tx_str),
            'net_io_raw': net_io
        })
    return containers


def collect_all_data():
    """Collect all host system data"""
    network = get_network_info()
    container_bw = get_container_bandwidth()

    # Update rolling bandwidth history
    update_bandwidth_history(network, container_bw)

    return {
        'system': get_system_info(),
        'cpu': get_cpu_info(),
        'gpu': get_gpu_info(),
        'lvm': get_lvm_info(),
        'raid': get_raid_status(),
        'disks': get_disk_layout(),
        'services': get_systemd_services(),
        'processes': get_process_list(),
        'network': network,
        'container_bandwidth': container_bw,
        'collected_at': datetime.now().isoformat(),
        'host': os.uname().nodename
    }


def write_data(data):
    """Write data to JSON file"""
    try:
        # Ensure directory exists
        Path(OUTPUT_FILE).parent.mkdir(parents=True, exist_ok=True)

        # Write directly to file (don't use rename - breaks Docker bind mounts)
        # Docker bind mounts track by inode, rename creates new inode
        with open(OUTPUT_FILE, 'w') as f:
            json.dump(data, f, indent=2)

        # Make readable by container
        os.chmod(OUTPUT_FILE, 0o644)

        print(f"[{datetime.now().strftime('%H:%M:%S')}] Updated {OUTPUT_FILE}")
        return True
    except Exception as e:
        print(f"Error writing data: {e}")
        return False


def main():
    global OUTPUT_FILE

    parser = argparse.ArgumentParser(description='A.R.C.H.I.E. Host System Monitor')
    parser.add_argument('--daemon', action='store_true', help='Run continuously')
    parser.add_argument('--interval', type=int, default=30, help='Update interval in seconds (default: 30)')
    parser.add_argument('--output', type=str, default=OUTPUT_FILE, help='Output file path')
    args = parser.parse_args()

    OUTPUT_FILE = args.output

    print("A.R.C.H.I.E. Host System Monitor")
    print(f"Output file: {OUTPUT_FILE}")
    print(f"Mode: {'Daemon (interval: {}s)'.format(args.interval) if args.daemon else 'Single run'}")
    print("-" * 50)

    if args.daemon:
        print("Starting daemon mode... (Ctrl+C to stop)")
        while True:
            try:
                data = collect_all_data()
                write_data(data)
                time.sleep(args.interval)
            except KeyboardInterrupt:
                print("\nStopping...")
                break
            except Exception as e:
                print(f"Error: {e}")
                time.sleep(5)
    else:
        data = collect_all_data()
        write_data(data)
        print("\nCollected data:")
        sys_info = data.get('system') or {}
        print(f"  Host: {sys_info.get('hostname', '?')} ({sys_info.get('distribution', '?')})")
        print(f"  Kernel: {sys_info.get('kernel', '?')}")
        print(f"  Uptime: {sys_info.get('uptime_formatted', '?')}")
        print(f"  Processes: {sys_info.get('process_count', '?')}, Users: {sys_info.get('users_logged_in', '?')}")
        cpu_info = data.get('cpu') or {}
        print(f"  CPU: {cpu_info.get('model', '?')} ({cpu_info.get('physical_cores', '?')}c/{cpu_info.get('logical_cores', '?')}t), Temp: {cpu_info.get('temperature', '?')}°C")
        gpu_info = data.get('gpu')
        if gpu_info:
            for g in gpu_info:
                print(f"  GPU: {g.get('model', '?')} ({g.get('vendor', '?')}), Temp: {g.get('temperature', '?')}°C, Driver: {g.get('driver', '?')}")
        else:
            print("  GPU: None detected")
        print(f"  Disks: {len(data['disks'])}")
        for d in data['disks']:
            print(f"    {d['device']}: {d['size_gb']} GB ({d['model']})")
        print(f"  LVM VGs: {len(data['lvm']['vgs']) if data['lvm'] else 0}")
        print(f"  LVM LVs: {len(data['lvm']['lvs']) if data['lvm'] else 0}")
        print(f"  RAID Arrays: {len(data['raid']['arrays']) if data['raid'] else 0}")
        print(f"  Processes: {len(data['processes'])} (top by CPU)")
        print(f"  Services: {len(data['services'])}")
        print(f"  Network: {data['network'].get('primary_ip', '?')} ({len(data['network']['interfaces'])} interfaces)")


if __name__ == '__main__':
    main()
