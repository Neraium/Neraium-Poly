#!/bin/bash
set -euo pipefail
# Synthetic copies only. All mounts disappear with this private namespace.
work=$(mktemp -d /home/ubuntu/phase51-isolation.XXXXXX)
chmod 755 "$work"
mkdir "$work/source" "$work/lower" "$work/upper" "$work/work" "$work/merged"
printf 'original\n' > "$work/source/fixture"
chmod 666 "$work/source/fixture"
ln "$work/source/fixture" "$work/lower/fixture"
mount --bind "$work/lower" "$work/lower"
mount -o remount,bind,ro "$work/lower"
mount --bind "$work/source" "$work/source"
mount -o remount,bind,ro "$work/source"
chown 1000:1000 "$work/upper" "$work/work"
mount -t overlay overlay -o "lowerdir=$work/lower,upperdir=$work/upper,workdir=$work/work,index=off,metacopy=off" "$work/merged"
setpriv --reuid=1000 --regid=1000 --init-groups --no-new-privs --bounding-set=-all python3 - "$work" <<'PY'
import errno, os, sys
from pathlib import Path
root=Path(sys.argv[1])
for spelling in ('source','lower'):
    try:
        fd=os.open(root/spelling/'fixture',os.O_WRONLY)
    except OSError as e:
        assert e.errno==errno.EROFS, str(e)
    else:
        os.close(fd)
        raise AssertionError('direct source write opened')
merged=root/'merged/fixture'
merged.write_text('only upper\n')
assert (root/'upper/fixture').read_text()=='only upper\n'
assert (root/'source/fixture').read_text()=='original\n'
assert (root/'source/fixture').stat().st_ino!=(root/'upper/fixture').stat().st_ino
print('Direct lower and source are read-only. Overlay copied up to a private inode.')
PY
umount "$work/merged"
umount "$work/lower"
umount "$work/source"
python3 - "$work" <<'PY'
import shutil,sys
from pathlib import Path
p=Path(sys.argv[1])
assert p.parent==Path('/home/ubuntu') and p.name.startswith('phase51-isolation.')
shutil.rmtree(p)
PY
