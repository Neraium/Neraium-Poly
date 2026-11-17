"""Exact persistent-byte limit for a single new native-evidence attempt.

All original directories remain untouched. Caller owns serial acquisition and
reserves only remaining bytes under the unchanged global64MiB guard. Network
response limits remain independently enforced by the existing client.
"""
from pathlib import PosixPath


class FileBudget:
    def __init__(self,directory,limit):
        self.root=PosixPath(directory).resolve();self.limit=limit;self.used=0;self.sizes={}
        if type(limit) is not int or limit<0:raise ValueError('invalid_native_disk_budget')
        if self.root.exists() and any(p.is_file() for p in self.root.rglob('*')):raise ValueError('new_native_attempt_directory_required')
    def write(self,path,data):
        plain=PosixPath(str(path))
        if plain.is_symlink() or not plain.resolve().is_relative_to(self.root):raise ValueError('unsafe_native_budget_path')
        if plain.exists() and str(plain) not in self.sizes:raise ValueError('unowned_native_evidence_write')
        size=len(data);old=self.sizes.get(str(plain),0)
        if self.used+size-old>self.limit:raise ValueError('native_remaining_disk_budget_exhausted')
        self.sizes[str(plain)]=size;self.used+=size-old  # Reserve before I/O; partial writes cannot under-account.
        result=plain.write_bytes(data)
        if result!=size:raise OSError('partial native evidence write')
        return result


class BudgetPath(PosixPath):
    def __init__(self,*parts,budget):
        super().__init__(*parts);self.budget=budget
    def with_segments(self,*parts):return type(self)(*parts,budget=self.budget)
    def write_bytes(self,data):return self.budget.write(self,data)
    def write_text(self,data,encoding=None,errors=None,newline=None):
        if newline is not None:data=data.replace('\n',newline)
        self.write_bytes(data.encode(encoding or 'utf-8',errors or 'strict'));return len(data)
