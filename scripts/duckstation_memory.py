"""Read-only, signature-verified PS1 RAM access. No host addresses are hardcoded."""
import ctypes,struct,time
from ctypes import wintypes as W
from pathlib import Path

REGISTER_BYTES = 128
REGISTER_SCAN_CHUNK = 64 * 1024
REGISTER_SCAN_LIMIT = 32 * 1024 * 1024
IMAGE_SCN_MEM_WRITE = 0x80000000

def _writable_sections_from_pe(data):
    """Return (name, RVA, mapped_size) for writable PE sections."""
    if len(data)<0x40:raise ValueError('Truncated PE image')
    u16=lambda n:struct.unpack_from('<H',data,n)[0]
    u32=lambda n:struct.unpack_from('<I',data,n)[0]
    pe=u32(0x3c)
    if data[pe:pe+4]!=b'PE\0\0':raise ValueError('Invalid PE signature')
    optional=pe+24
    if u16(optional)!=0x20b:raise ValueError('Expected x64 PE')
    section_count=u16(pe+6)
    section_table=optional+u16(pe+20)
    if section_table+section_count*40>len(data):raise ValueError('Truncated PE section table')
    found=[]
    for i in range(section_count):
        s=section_table+40*i
        characteristics=u32(s+36)
        if not characteristics&IMAGE_SCN_MEM_WRITE:continue
        name=data[s:s+8].split(b'\0',1)[0].decode('ascii','replace')
        rva=u32(s+12)
        size=max(u32(s+8),u32(s+16))
        if size:found.append((name,rva,size))
    return found

def _writable_pe_sections(path):
    return _writable_sections_from_pe(Path(path).read_bytes())

def _validate_register_anchor(anchor):
    if not isinstance(anchor,bytes) or len(anchor)!=REGISTER_BYTES:
        raise ValueError('Register anchor must be exactly 128 bytes')
    groups=[anchor[i:i+4] for i in range(0,len(anchor),4)]
    nonzero=sum(value!=0 for value in anchor)
    if nonzero<16 or len(set(anchor))<4 or len(set(groups))<4:
        raise ValueError('Register anchor is zero or low entropy')
    return anchor

def data_exports(path):
    data=Path(path).read_bytes();u16=lambda n:struct.unpack_from('<H',data,n)[0];u32=lambda n:struct.unpack_from('<I',data,n)[0]
    pe=u32(0x3c);assert data[pe:pe+4]==b'PE\0\0'
    optional=pe+24;assert u16(optional)==0x20b,'Expected x64 PE'
    sections=optional+u16(pe+20)
    def offset(rva):
        for i in range(u16(pe+6)):
            s=sections+40*i;va=u32(s+12);size=u32(s+16)
            if va<=rva<va+size:return u32(s+20)+rva-va
        raise ValueError('Unmapped export RVA')
    table=offset(u32(optional+112));count=u32(table+24);assert count<65536
    functions=offset(u32(table+28));names=offset(u32(table+32));ordinals=offset(u32(table+36));found={}
    for i in range(count):
        at=offset(u32(names+4*i));name=data[at:data.index(b'\0',at)].decode('ascii')
        if name in ('RAM','RAM_SIZE','RAM_MASK'):found[name]=u32(functions+4*u16(ordinals+2*i))
    assert len(found)==3,'Expected stock DuckStation RAM exports'
    return found

class MemoryInfo(ctypes.Structure):
    _fields_=[('base',ctypes.c_void_p),('allocation',ctypes.c_void_p),
              ('allocation_protect',W.DWORD),('partition',W.WORD),
              ('size',ctypes.c_size_t),('state',W.DWORD),('protect',W.DWORD),('type',W.DWORD)]

class ReadOnlyRAM:
    def __init__(self,pid,anchors,executable=None):
        self.k=ctypes.WinDLL('kernel32',use_last_error=True)
        self.k.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];self.k.OpenProcess.restype=W.HANDLE
        self.k.ReadProcessMemory.argtypes=[W.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
        self.k.VirtualQueryEx.argtypes=[W.HANDLE,ctypes.c_void_p,ctypes.POINTER(MemoryInfo),ctypes.c_size_t]
        self.k.VirtualQueryEx.restype=ctypes.c_size_t
        self.k.CloseHandle.argtypes=[W.HANDLE]
        self.handle=self.k.OpenProcess(0x400|0x10,False,pid) # QUERY_INFORMATION | VM_READ only
        if not self.handle:raise ctypes.WinError(ctypes.get_last_error())
        self.base=None;self.matches=[];self.module_base=None;self.executable_path=None
        self.writable_sections=[];self.registers_address=None
        try:
            if executable is not None:
                psapi=ctypes.WinDLL('psapi',use_last_error=True)
                psapi.EnumProcessModulesEx.argtypes=[W.HANDLE,ctypes.POINTER(ctypes.c_void_p),W.DWORD,ctypes.POINTER(W.DWORD),W.DWORD]
                modules=(ctypes.c_void_p*1024)();needed=W.DWORD()
                if not psapi.EnumProcessModulesEx(self.handle,modules,ctypes.sizeof(modules),ctypes.byref(needed),2):raise ctypes.WinError(ctypes.get_last_error())
                psapi.GetModuleFileNameExW.argtypes=[W.HANDLE,ctypes.c_void_p,W.LPWSTR,W.DWORD]
                name=ctypes.create_unicode_buffer(32768)
                psapi.GetModuleFileNameExW(self.handle,modules[0],name,len(name))
                self.executable_path=Path(executable).resolve()
                assert Path(name.value).resolve()==self.executable_path,'Unexpected process module'
                self.module_base=int(modules[0])
                self.writable_sections=_writable_pe_sections(self.executable_path)
                exports=data_exports(self.executable_path)
                self.ram_export_address=self.module_base+exports['RAM']
                self.base=struct.unpack('<Q',self.read_host(self.ram_export_address,8))[0]
                size=struct.unpack('<I',self.read_host(self.module_base+exports['RAM_SIZE'],4))[0]
                assert size==0x200000 and self.base,'Expected active 2 MiB RAM'
                assert all(self.read_host(self.base+o,len(v))==v for o,v in anchors),'RAM export anchor mismatch'
                self.matches=[self.base];self.regions_examined=0;self.method='exported_RAM'
                return
            address=0;deadline=time.monotonic()+12;regions=0
            while address<0x00007fffffff0000:
                if time.monotonic()>deadline:raise RuntimeError('RAM discovery time limit')
                info=MemoryInfo()
                if not self.k.VirtualQueryEx(self.handle,ctypes.c_void_p(address),ctypes.byref(info),ctypes.sizeof(info)):break
                base=info.base or 0;size=info.size;regions+=1
                if info.state==0x1000 and not info.protect&0x100 and (info.protect&0xff) in (4,8,0x40,0x80) and size>=0x200000:
                    # Probe the region start only; do not scan arbitrary application contents.
                    try:
                        if all(self.read_host(base+offset,len(value))==value for offset,value in anchors):
                            self.matches.append(base)
                    except OSError:pass
                if base+size<=address:break
                address=base+size
            if not self.matches:raise RuntimeError('No readable RAM region matches all paused-game anchors')
            self.base=self.matches[0];self.regions_examined=regions
        except BaseException:self.close();raise

    def discover_registers(self,anchor):
        """Find one exact 128-byte paused GDB register anchor in writable PE data.

        The return value is a host address. This only locates the byte block;
        callers must independently verify its relation to GDB's register layout.
        """
        self.registers_address=None
        anchor=_validate_register_anchor(anchor)
        if self.module_base is None or self.executable_path is None:
            raise RuntimeError('Register discovery requires a verified executable module')
        total=sum(size for _,_,size in self.writable_sections)
        if total>REGISTER_SCAN_LIMIT:
            raise RuntimeError(f'Writable PE scan is {total} bytes; limit is {REGISTER_SCAN_LIMIT}')
        matches=set()
        overlap=len(anchor)-1
        step=REGISTER_SCAN_CHUNK-overlap
        for name,rva,size in self.writable_sections:
            section_base=self.module_base+rva
            offset=0
            while offset<size:
                length=min(REGISTER_SCAN_CHUNK,size-offset)
                block=self.read_host(section_base+offset,length)
                cursor=0
                while True:
                    found=block.find(anchor,cursor)
                    if found<0:break
                    matches.add(section_base+offset+found)
                    if len(matches)>1:
                        addresses=', '.join(f'{address:#x}' for address in sorted(matches))
                        raise RuntimeError(f'Ambiguous register anchor in writable PE sections: {addresses}')
                    cursor=found+1
                if length<=overlap:break
                offset+=min(step,length)
            if len(matches)>1:break
        if not matches:
            raise RuntimeError('Register anchor was not found in writable PE sections')
        self.registers_address=next(iter(matches))
        return self.registers_address

    def read_registers(self):
        """Read the located 128-byte block without decoding register semantics."""
        if self.registers_address is None:
            raise RuntimeError('Call discover_registers() before read_registers()')
        return self.read_host(self.registers_address,REGISTER_BYTES)

    def read_program_counter(self):
        # Pinned DuckStation 3b30876e: 35 GPR words (including HI/LO and
        # dummy load slot) followed by 11 COP0 words. Verify against GDB
        # before using this source-derived layout for any screen classifier.
        if self.registers_address is None:
            raise RuntimeError('Register discovery is required')
        return struct.unpack('<I',self.read_host(self.registers_address+0xb8,4))[0]

    def read_host(self,address,size):
        buffer=ctypes.create_string_buffer(size);count=ctypes.c_size_t()
        if not self.k.ReadProcessMemory(self.handle,ctypes.c_void_p(address),buffer,size,ctypes.byref(count)) or count.value!=size:
            raise ctypes.WinError(ctypes.get_last_error())
        return buffer.raw

    def read(self,address,size):
        offset=address-0x80000000
        if not 0<=offset<=0x200000-size:raise ValueError('Read outside verified PS1 RAM')
        return self.read_host(self.base+offset,size)

    def is_running(self):
        code=W.DWORD()
        self.k.GetExitCodeProcess.argtypes=[W.HANDLE,ctypes.POINTER(W.DWORD)]
        return bool(self.k.GetExitCodeProcess(self.handle,ctypes.byref(code))) and code.value==259

    def ram_available(self):
        if not self.is_running():return False
        try:
            pointer=struct.unpack('<Q',self.read_host(self.ram_export_address,8))[0]
            return bool(pointer) and pointer==self.base
        except OSError:return False

    def close(self):
        if self.handle:self.k.CloseHandle(self.handle);self.handle=None
