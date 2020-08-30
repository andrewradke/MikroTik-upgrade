#!/usr/bin/python3

import sys
import os
import shutil
import re
import time
import getpass
import packaging.version

import paramiko
import scp


import argparse
parser = argparse.ArgumentParser()
parser.add_argument('-V', '--version',   required=True,		help='RouterOS version to install')
parser.add_argument('-d', '--downgrade', action="store_true",	help='Allow downgrades, default: false')
parser.add_argument('-t', '--timeout',				help='SSH timeout in seconds, default: 10')
parser.add_argument('-s', '--sshstop',   action="store_true",	help='Stop upgrades of further devices if SSH fails on initial connection, default: false')
parser.add_argument('-R', '--sshretries',			help='SSH retries, default: 3')
parser.add_argument('-r', '--reboot_timeout',			help='Timeout after reboot before upgrade considered failed, default: 180')
parser.add_argument('-u', '--username',				help='Username for access to RouterOS, default: local username')
parser.add_argument('-b', '--baseurl',				help='Base URL for retrieving RouterOS images if needed, default: https://download.mikrotik.com/routeros/')
parser.add_argument('-D', '--download',  action="store_true",	help="Download updates if existing image isn't found")
parser.add_argument('-f', '--firmware',  action="store_true",	help="Upgrade firmware after doing RouterOS upgrade")
parser.add_argument('-n', '--noop',      action="store_true",	help="Don't perform any actions, just report what will occur. Implies --verbose")
parser.add_argument('-v', '--verbose',   action="count",	help='Verbose output')
parser.add_argument('hosts', metavar='HOST', type=str, nargs='+', help='RouterOS host to upgrade')
args = parser.parse_args()

class bcolors:
	HEADER = '\033[95m'
	OKBLUE = '\033[94m'
	OKGREEN = '\033[92m'
	WARNING = '\033[93m'
	FAIL = '\033[91m'
	ENDC = '\033[0m'
	BOLD = '\033[1m'
	UNDERLINE = '\033[4m'


pingable = os.system("fping -q localhost")
if pingable == 127:
	print("fping is required to be able check for the RouterOS device connectivity after rebooting")
	sys.exit(1)

if args.username:
	username = args.username
else:
	username = getpass.getuser()

if args.timeout:
	timeout = args.timeout
else:
	timeout = 10

if args.sshretries:
	sshretries = args.sshretries
else:
	sshretries = 10

if args.reboot_timeout:
	reboot_timeout = int(args.reboot_timeout)
else:
	reboot_timeout = 180

if args.baseurl:
	baseurl = args.baseurl
else:
	baseurl = "https://download.mikrotik.com/routeros/"

if args.noop:
	if not args.verbose:
		args.verbose = 1

if args.verbose:
	print("Verbose output enabled")
	print("Verbose level {}".format(args.verbose))
	print("Username: '{}'".format(username))
	print("Timeout: {} seconds".format(timeout))
	print("Upgrading to RouterOS {}".format(args.version))
	if args.downgrade:
		print("Downgrades allowed")
	if args.firmware:
		print("Upgrading firmware if available")
	if args.noop:
		print("Dry run only. NOT performing any actions.")

NewVersion = packaging.version.parse(args.version)


MikroTik_regex = re.compile('^ *([^:]*): (.*)')
MikroTik_version_regex = re.compile('^([^ ]*)')


# setup logging
#paramiko.util.log_to_file("demo.log")


# Define progress callback that prints the current percentage completed for the file with SCP
def progress(filename, size, sent):
	sys.stdout.write("%s\'s progress: %.2f%%   \r" % (filename, float(sent)/float(size)*100) )

# Define reporthook that prints the current percentage completed for the file download
def reporthook(chunknum, maxchunksize, totalsize):
	sys.stdout.write("%i of %i progress: %.2f%%   \r" % ((chunknum*maxchunksize), totalsize, float(chunknum*maxchunksize)/float(totalsize)*100) )


for hostname in args.hosts:
	if sys.stdout.isatty():
		print(bcolors.BOLD + bcolors.UNDERLINE, end='')
	print("\n*** {} ***".format(hostname))
	if sys.stdout.isatty():
		print(bcolors.ENDC, end='')
	if args.verbose:
		print("Checking RouterOS version")
	version	= ""
	architecture_name = ""
	board_name = ""
	bad_blocks = ""

	SSHClient = paramiko.SSHClient()
	try:
		# Try loading system wide known_hosts
		SSHClient.load_system_host_keys("/etc/ssh/ssh_known_hosts")
	except:
		pass
	# Add the users known_hosts
	SSHClient.load_system_host_keys()

	connected = False
	retries   = 0
	while not connected:
		try:
			SSHClient.connect(hostname, username=username, timeout=timeout)
			connected = True
			break
		except:
			if retries > sshretries:
				break
			print(bcolors.WARNING + "SSH connection failed. Retrying." + bcolors.ENDC)
			retries += 1
			time.sleep(retries)
	if not connected:
		if sys.stdout.isatty():
			print(bcolors.FAIL, end='')
		print("ERROR: SSH connection failed.")
		if args.sshstop:
			print("Updates to ALL FURTHER devices cancelled!")
		if sys.stdout.isatty():
			print(bcolors.ENDC, end='')
		SSHClient.close()
		if not args.sshstop:
			continue
		if not args.noop:
			sys.exit(2)
		else:
			print(bcolors.WARNING + "NOOP: skipping to next host due to being a dry run" + bcolors.ENDC)
			continue

	stdin, stdout, stderr = SSHClient.exec_command('/system resource print')

	for line in stdout:
		line = line.rstrip('\r\n')
		if args.verbose and args.verbose >= 3:
			print('... ' + line)
		m = MikroTik_regex.match(line)
		if m:
			if (m.group(1) == 'version'):
				version = m.group(2)
			if (m.group(1) == 'architecture-name'):
				architecture_name = m.group(2)
			if (m.group(1) == 'board-name'):
				board_name = m.group(2)
			if (m.group(1) == 'bad-blocks'):
				bad_blocks = m.group(2)

	if args.verbose and args.verbose >= 2:
		print("\tversion: " + version)
		print("\tarchitecture-name: " + architecture_name)
		print("\tboard-name: " + board_name)
		print("\tbad-blocks: " + bad_blocks)

	if (version == ""):
		print("Failed to get current RouterOS version. Skipping upgrade.")
		SSHClient.close()
		continue
	else:
		m = MikroTik_version_regex.match(version)
		if m:
			version = m.group(1)
		CurVersion = packaging.version.parse(version)

	if (architecture_name == ""):
		print("Failed to get RouterOS architecture-name. Skipping upgrade.")
		SSHClient.close()
		continue

	if (board_name == "CHR"):
		architecture_name = "x86"
	else:
		if (bad_blocks == ""):
			print("Failed to get current bad-blocks. Skipping upgrade.")
			SSHClient.close()
			continue
		if (bad_blocks != "0%"):
			print('bad-blocks of {} is not 0%. Skipping upgrade.'.format(bad_blocks))
			SSHClient.close()
			continue

	if (CurVersion < NewVersion):
		action = "Upgrading"
	elif (CurVersion > NewVersion) and args.downgrade:
		action = "Downgrading"
	else:
		action = None

	if action:
		print("{} RouterOS version from {} to {}".format(action,version,args.version))

		filename = "routeros-" + architecture_name + "-" + args.version + ".npk"
		if not os.path.isfile(filename) and args.download:
			fullurl = baseurl + "/" + args.version + "/" + filename
			print("Downloading RouterOS image file {}".format(fullurl))
			import urllib.request
			try:
				if sys.stdout.isatty():
					urllib.request.urlretrieve(fullurl, filename, reporthook=reporthook)
					print('\r', end='')
					for i in range(0,shutil.get_terminal_size().columns):
						print(' ', end='')
					print('\r', end='')
				else:
					urllib.request.urlretrieve(fullurl, filename)
			except urllib.error.URLError as e:
				print("Failed to download '{}': {} {}".format(fullurl, e.code, e.reason))

		if os.path.isfile(filename):
			if sys.stdout.isatty():
				SCPClient = scp.SCPClient(SSHClient.get_transport(), progress=progress, socket_timeout=60)
			else:
				SCPClient = scp.SCPClient(SSHClient.get_transport())
			if not args.noop:
				SCPClient.put(filename)
				if sys.stdout.isatty():
					print('\r', end='')
					for i in range(0,shutil.get_terminal_size().columns):
						print(' ', end='')
					print('\r', end='')
			else:
				print(bcolors.OKBLUE + "NOOP: would upload {}".format(filename) + bcolors.ENDC)
			if args.verbose:
				print()
			SCPClient.close()

			print("Rebooting {}".format(hostname))
			if not args.noop:
				stdin, stdout, stderr = SSHClient.exec_command('/system reboot')
			else:
				print(bcolors.OKBLUE + "NOOP: would reboot" + bcolors.ENDC)
			SSHClient.close()

			reboot_time = time.time()

			# Give the device at least 5 seconds to reboot before starting to check whether it's alive
			if not args.noop:
				time.sleep(10)

			host_up = False
			timeout = time.time() + reboot_timeout
			while time.time() < timeout:
				pingable = os.system("fping -q " + hostname + " 2>/dev/null")
				if pingable == 0:
					host_up = True
					break
				if sys.stdout.isatty():
					print('\r{:.0f} seconds since reboot...'.format(time.time() - reboot_time), end='', flush=True)
			if sys.stdout.isatty():
				print('\r', end='')
				for i in range(0,shutil.get_terminal_size().columns):
					print(' ', end='')
				print('\r', end='')

			if host_up:
				reboot_time = time.time() - reboot_time
				print('{} is back online after {:.0f} seconds. Checking status'.format(hostname, reboot_time), end='', flush=True)
				time.sleep(5)	# Wait 5 seconds for the device to fully boot

				version	= ""
				uptime	= ""
				CurVersion = ""
				connected = False
				retries   = 0
				while not connected:
					try:
						SSHClient.connect(hostname, username=username, timeout=timeout)
						connected = True
						break
					except paramiko.SSHException as e:
						if retries > sshretries:
							break
						print(bcolors.WARNING + "SSH connection failed with '{}'. Retrying.".format(e) + bcolors.ENDC)
						retries += 1
						time.sleep(retries)
				if not connected:
					if sys.stdout.isatty():
						print(bcolors.FAIL, end='')
					print("ERROR: SSH connection failed. Updates to ALL FURTHER devices cancelled!")
					if sys.stdout.isatty():
						print(bcolors.ENDC, end='')
					SSHClient.close()
					if not args.noop:
						sys.exit(2)
					else:
						print(bcolors.WARNING + "NOOP: skipping to next host due to being a dry run" + bcolors.ENDC)
						continue

				stdin, stdout, stderr = SSHClient.exec_command('/system resource print')

				for line in stdout:
					line = line.rstrip('\r\n')
					if args.verbose and args.verbose >= 3:
						print('... ' + line)
					m = MikroTik_regex.match(line)
					if m:
						if (m.group(1) == 'version'):
							version = m.group(2)
						if (m.group(1) == 'uptime'):
							uptime = m.group(2)

				if (version == ""):
					if sys.stdout.isatty():
						print(bcolors.FAIL, end='')
					print("ERROR: Could not confirm RouterOS version. Updates to ALL FURTHER devices cancelled!")
					if sys.stdout.isatty():
						print(bcolors.ENDC, end='')
					SSHClient.close()
					if not args.noop:
						sys.exit(2)
					else:
						print(bcolors.WARNING + "NOOP: continuing due to being a dry run" + bcolors.ENDC)

				m = MikroTik_version_regex.match(version)
				if m:
					version = m.group(1)
				CurVersion = packaging.version.parse(version)
				if (CurVersion < NewVersion):
					if sys.stdout.isatty():
						print(bcolors.FAIL, end='')
					print("ERROR: Upgrade of {} did not occur, current RouterOS version {}. Updates to ALL FURTHER devices cancelled!".format(hostname,version))
					if sys.stdout.isatty():
						print(bcolors.ENDC, end='')
					SSHClient.close()
					if not args.noop:
						sys.exit(2)
					else:
						print(bcolors.WARNING + "NOOP: continuing due to being a dry run" + bcolors.ENDC)
				else:
					if sys.stdout.isatty():
						print(bcolors.OKGREEN, end='')
					print("{} RouterOS successfully upgraded. Version now {}".format(hostname,version))
					if sys.stdout.isatty():
						print(bcolors.ENDC, end='')

			else:
				if sys.stdout.isatty():
					print(bcolors.FAIL, end='')
				print("ERROR: {} has NOT come back online within {} seconds. Updates to ALL FURTHER devices cancelled!".format(hostname,reboot_timeout))
				if sys.stdout.isatty():
					print(bcolors.ENDC, end='')
				if not args.noop:
					sys.exit(2)
				else:
					print(bcolors.WARNING + "NOOP: continuing due to being a dry run" + bcolors.ENDC)

		else:
			print(filename + " doesn't exist or isn't a file. Skipping upgrade.")
	else:
		print("RouterOS version already {}".format(version))

	if args.firmware and board_name != "CHR":
		if args.verbose:
			print("Checking firmware version".format(hostname))
		CurrentFirmware = ""
		UpgradeFirmware = ""
		connected = False
		retries   = 0
		while not connected:
			try:
				SSHClient.connect(hostname, username=username, timeout=timeout)
				connected = True
				break
			except paramiko.SSHException as e:
				if retries > sshretries:
					break
				print(bcolors.WARNING + "SSH connection failed with '{}'. Retrying.".format(e) + bcolors.ENDC)
				retries += 1
				time.sleep(retries)
		if not connected:
			if sys.stdout.isatty():
				print(bcolors.FAIL, end='')
			print("ERROR: SSH connection failed. Updates to ALL FURTHER devices cancelled!")
			if sys.stdout.isatty():
				print(bcolors.ENDC, end='')
			SSHClient.close()
			if not args.noop:
				sys.exit(2)
			else:
				print(bcolors.WARNING + "NOOP: skipping to next host due to being a dry run" + bcolors.ENDC)
				continue

		stdin, stdout, stderr = SSHClient.exec_command('/system routerboard print')

		for line in stdout:
			line = line.rstrip('\r\n')
			if args.verbose and args.verbose >= 3:
				print('... ' + line)
			m = MikroTik_regex.match(line)
			if m:
				if (m.group(1) == 'current-firmware'):
					CurrentFirmware = m.group(2)
				if (m.group(1) == 'upgrade-firmware'):
					UpgradeFirmware = m.group(2)

		if (CurrentFirmware == "" or UpgradeFirmware == ""):
			if sys.stdout.isatty():
				print(bcolors.FAIL, end='')
			print("ERROR: Could not get firmware versions. Updates to ALL FURTHER devices cancelled!")
			if sys.stdout.isatty():
				print(bcolors.ENDC, end='')
			SSHClient.close()
			if not args.noop:
				sys.exit(2)
			else:
				print(bcolors.WARNING + "NOOP: continuing due to being a dry run" + bcolors.ENDC)

		NewVersion = packaging.version.parse(UpgradeFirmware)
		CurVersion = packaging.version.parse(CurrentFirmware)
		if (CurVersion < NewVersion):
			print("Upgrading firmware from {} to {}".format(CurrentFirmware,UpgradeFirmware))
			if not args.noop:
				stdin, stdout, stderr = SSHClient.exec_command('/system routerboard upgrade')
				if args.verbose:
					print("rebooting in 5 seconds.")
				time.sleep(5)
				print("Rebooting {}".format(hostname))
				stdin, stdout, stderr = SSHClient.exec_command('/system reboot')
			else:
				print(bcolors.OKBLUE + "NOOP: would upgrade routerboard and reboot" + bcolors.ENDC)
			SSHClient.close()

			reboot_time = time.time()

			# Give the device at least 5 seconds to reboot before starting to check whether it's alive
			if not args.noop:
				time.sleep(10)

			host_up = False
			timeout = time.time() + reboot_timeout
			while time.time() < timeout:
				pingable = os.system("fping -q " + hostname + " 2>/dev/null")
				if pingable == 0:
					host_up = True
					break
				if sys.stdout.isatty():
					print('\r{:.0f} seconds since reboot...'.format(time.time() - reboot_time), end='', flush=True)
			if sys.stdout.isatty():
				print('\r', end='')
				for i in range(0,shutil.get_terminal_size().columns):
					print(' ', end='')
				print('\r', end='')

			if host_up:
				reboot_time = time.time() - reboot_time
				print('{} is back online after {:.0f} seconds. Checking status'.format(hostname, reboot_time), end='', flush=True)
				time.sleep(5)	# Wait 5 seconds for the device to fully boot

				version	= ""
				uptime	= ""
				CurVersion = ""
				connected = False
				retries   = 0
				while not connected:
					try:
						SSHClient.connect(hostname, username=username, timeout=timeout)
						connected = True
						break
					except paramiko.SSHException as e:
						if retries > sshretries:
							break
						print(bcolors.WARNING + "SSH connection failed with '{}'. Retrying.".format(e) + bcolors.ENDC)
						retries += 1
						time.sleep(retries)
				if not connected:
					if sys.stdout.isatty():
						print(bcolors.FAIL, end='')
					print("ERROR: SSH connection failed. Updates to ALL FURTHER devices cancelled!")
					if sys.stdout.isatty():
						print(bcolors.ENDC, end='')
					SSHClient.close()
					if not args.noop:
						sys.exit(2)
					else:
						print(bcolors.WARNING + "NOOP: skipping to next host due to being a dry run" + bcolors.ENDC)
						continue

				stdin, stdout, stderr = SSHClient.exec_command('/system routerboard print')

				for line in stdout:
					line = line.rstrip('\r\n')
					if args.verbose and args.verbose >= 3:
						print('... ' + line)
					m = MikroTik_regex.match(line)
					if m:
						if (m.group(1) == 'current-firmware'):
							CurrentFirmware = m.group(2)
						if (m.group(1) == 'upgrade-firmware'):
							UpgradeFirmware = m.group(2)

				if (CurrentFirmware == "" or UpgradeFirmware == ""):
					if sys.stdout.isatty():
						print(bcolors.FAIL, end='')
					print("ERROR: Could not confirm firmware versions. Updates to ALL FURTHER devices cancelled!")
					if sys.stdout.isatty():
						print(bcolors.ENDC, end='')
					SSHClient.close()
					if not args.noop:
						sys.exit(2)
					else:
						print(bcolors.WARNING + "NOOP: continuing due to being a dry run" + bcolors.ENDC)

				NewVersion = packaging.version.parse(UpgradeFirmware)
				CurVersion = packaging.version.parse(CurrentFirmware)
				if (CurVersion < NewVersion):
					if sys.stdout.isatty():
						print(bcolors.FAIL, end='')
					print("ERROR: Upgrade of {} firmware did not occur, current version {}, upgrade version {}. Updates to ALL FURTHER devices cancelled!".format(hostname,CurrentFirmware,UpgradeFirmware))
					if sys.stdout.isatty():
						print(bcolors.ENDC, end='')
					SSHClient.close()
					if not args.noop:
						sys.exit(2)
					else:
						print(bcolors.WARNING + "NOOP: continuing due to being a dry run" + bcolors.ENDC)
				else:
					if sys.stdout.isatty():
						print(bcolors.OKGREEN, end='')
					print("{} firmware successfully upgraded. Version now {}".format(hostname,CurrentFirmware))
					if sys.stdout.isatty():
						print(bcolors.ENDC, end='')
			else:
				if sys.stdout.isatty():
					print(bcolors.FAIL, end='')
				print("ERROR: {} has NOT come back online within {} seconds. Updates to ALL FURTHER devices cancelled!".format(hostname,reboot_timeout))
				if sys.stdout.isatty():
					print(bcolors.ENDC, end='')
				if not args.noop:
					sys.exit(2)
				else:
					print(bcolors.WARNING + "NOOP: continuing due to being a dry run" + bcolors.ENDC)
		else:
			print("firmware version already {}".format(CurrentFirmware))

	SSHClient.close()
	print()
