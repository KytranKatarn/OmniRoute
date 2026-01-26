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
    """Get host network information"""
    info = {
        'hostname': '',
        'interfaces': [],
        'primary_ip': None
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

    return info


def get_disk_layout():
    """Get host disk and partition layout"""
    disks = []

    # Use lsblk to get disk info
    output = run_command(['lsblk', '-J', '-b', '-o', 'NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,PKNAME,MODEL'])
    if output:
        try:
            import json
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
        except:
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

    return disks


def collect_all_data():
    """Collect all host system data"""
    return {
        'lvm': get_lvm_info(),
        'raid': get_raid_status(),
        'disks': get_disk_layout(),
        'services': get_systemd_services(),
        'network': get_network_info(),
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
        print(f"  LVM VGs: {len(data['lvm']['vgs']) if data['lvm'] else 0}")
        print(f"  LVM LVs: {len(data['lvm']['lvs']) if data['lvm'] else 0}")
        print(f"  RAID Arrays: {len(data['raid']['arrays']) if data['raid'] else 0}")
        print(f"  Services: {len(data['services'])}")
        print(f"  Network Interfaces: {len(data['network']['interfaces'])}")


if __name__ == '__main__':
    main()
