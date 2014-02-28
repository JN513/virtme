#!/usr/bin/python3
# -*- mode: python -*-
# virtme-mkinitramfs: Generate an initramfs image for virtme
# Copyright © 2014 Andy Lutomirski
# Licensed under the GPLv2, which is available in the virtme distribution
# as a file called LICENSE with SHA-256 hash:
# 8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643

import shutil
import cpiowriter
import inspect
import io
import os.path
import shlex
import modfinder
import virtmods

def make_base_layout(cw):
    for dir in (b'lib', b'bin', b'var', b'etc', b'newroot', b'dev', b'tmproot'):
        cw.mkdir(dir, 0o755)

    cw.symlink(b'bin', b'sbin')
    cw.symlink(b'lib', b'lib64')

def make_dev_nodes(cw):
    cw.mkchardev(b'dev/null', (1, 3), mode=0o666)
    cw.mkchardev(b'dev/console', (5, 1), mode=0o660)

def install_busybox(cw):
    bbpath = shutil.which('busybox')
    with open(bbpath, 'rb') as busybox:
        cw.write_file(name=b'bin/busybox', body=busybox, mode=0o755)

    for tool in ('sh', 'mount', 'umount', 'switch_root', 'sleep', 'mkdir',
                 'mknod', 'insmod'):
        cw.symlink(b'busybox', ('bin/%s' % tool).encode('ascii'))

    cw.mkdir(b'bin/real_progs', mode=0o755)

def install_modprobe(cw):
    cw.write_file(name=b'bin/modprobe', body=b'\n'.join([
        b'#!/bin/sh',
        b'echo "virtme: initramfs does not have module $3" >/dev/console',
    ]), mode=0o755)

def install_modules(cw, modfiles):
    cw.mkdir(b'modules', 0o755)
    paths = []
    for mod in modfiles:
        with open(mod, 'rb') as f:
            modpath = 'modules/' + os.path.basename(mod)
            paths.append(modpath)
            cw.write_file(name=modpath.encode('ascii'),
                          body=f, mode=0o644)

    script = '\n'.join('echo \'Loading %s...\'; insmod %s' %
                       (os.path.basename(p), shlex.quote(p)) for p in paths)
    cw.write_file(name=b'modules/load_all.sh',
                  body=script.encode('ascii'), mode=0o644)

_INIT = """#!/bin/sh

source /modules/load_all.sh

echo 'Mounting hostfs...'

if ! /bin/mount -n -t 9p -o ro,version=9p2000.L,trans=virtio,access=any virtme.root /newroot/; then
  echo "Failed to switch to real root.  We are stuck."
  sleep 5
  exit 1
fi

# Can we actually use /newroot/ as root?
if ! mount -t proc -o nosuid,noexec,nodev proc /newroot/proc 2>/dev/null; then
  # QEMU 1.5 and below have a bug in virtfs that prevents mounting
  # anything on top of a virtfs mount.
  echo "virtme: your host's virtfs is broken -- using a fallback tmpfs"

  mount --move /newroot /tmproot
  mount -t tmpfs root_workaround /newroot/
  cd tmproot
  mkdir /newroot/proc /newroot/sys /newroot/dev /newroot/run /newroot/tmp
  for i in *; do
    if [[ -d "$i" && \! -d "/newroot/$i" ]]; then
      mkdir /newroot/"$i"
      mount --bind "$i" /newroot/"$i"
    fi
  done
  mknod /newroot/dev/null c 1 3
  mount -o remount,ro -t tmpfs root_workaround /newroot
  umount -l /tmproot
else
  umount /newroot/proc  # Don't leave garbage behind
fi

echo 'Initramfs is done; switching to real root'
exec /bin/switch_root /newroot {hostfsroot}
"""

def generate_init():
    mypath = os.path.dirname(os.path.abspath(
        inspect.getfile(inspect.currentframe())))

    out = io.StringIO()
    out.write(_INIT.format(hostfsroot=shlex.quote(os.path.join(
        mypath, 'virtme-init'))))
    return out.getvalue().encode('utf-8')

def mkinitramfs(out, modfiles=[]):
    cw = cpiowriter.CpioWriter(out)
    make_base_layout(cw)
    make_dev_nodes(cw)
    install_busybox(cw)
    install_modprobe(cw)
    if modfiles is not None:
        install_modules(cw, modfiles)
    cw.write_file(b'init', body=generate_init(), mode=0o755)
    cw.write_trailer()
